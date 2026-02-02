import configparser
import sys
import time
from datetime import datetime
from heapq import heappop, heappush
from itertools import chain

from numpy.random import SeedSequence, default_rng

import conf
import policy
import probabilistic
import probabilistic_carbon_aware
import stateful
from arrivals import ArrivalProcess
from co2_footprint import compute_local_emissions, compute_cloud_emissions, compute_edge_emissions, \
    compute_transmission_energy_edge, compute_transmission_energy_cloud
from faas import *
from infrastructure import *
from policy import SchedulerDecision, add_enum_members
from stateful import key_locator
from statistics import Stats
from utils import plot


@dataclass
class Event:
    canceled: bool = field(default=False, init=False)

    # XXX: ugly workaround to avoid issues with the heapq (in case of events
    # scheduled at the same time)
    def __lt__(self, other):
        return True

    def __le__(self, other):
        return True


@dataclass
class Arrival(Event):
    node: Node
    function: Function
    qos_class: QoSClass
    arrival_proc: ArrivalProcess = None
    offloaded_from: [Node] = field(default_factory=list)
    original_arrival_time: float = None


@dataclass
class Completion(Event):
    arrival: float
    function: Function
    qos_class: QoSClass
    node: Node
    cold: bool
    exec_time: float
    offloaded_from: [Node] = None
    data_access_time: float = 0.0

@dataclass
class CheckExpiredContainers(Event):
    node: Node


@dataclass
class CarbonIntensityUpdate(Event):
    pass

@dataclass
class PolicyUpdate(Event):
    pass


@dataclass
class ArrivalRateUpdate(Event):
    pass


@dataclass
class StatPrinter(Event):
    pass

@dataclass
class DispatcherUpdate(Event):
    pass

@dataclass
class NodeUtilizationUpdate(Event):
    pass

@dataclass
class LatencyUpdate(Event):
    pass

OFFLOADING_OVERHEAD = 0.005
ARRIVAL_TRACE_PERIOD = 60.0
KWH = 3600*1000

@dataclass
class Simulation:
    config: configparser.ConfigParser
    seed_sequence: SeedSequence
    infra: Infrastructure
    functions: [Function]
    classes: [QoSClass]
    node2arrivals: dict
    function_variants: {Function: [Function]}
    variants: [Variant]

    end_date_co2_emissions = datetime.strptime("2023-01-06", "%Y-%m-%d")


    def __post_init__(self):
        assert (len(self.functions) > 0)
        assert (len(self.classes) > 0)

        self.__event_counter = 0

        self.stats = Stats(self, self.functions, self.classes, self.infra)

        self.first_stat_print = True
        self.external_arrivals_allowed = True

        self.verbosity = self.config.getint(conf.SEC_SIM, conf.VERBOSITY, fallback=0)
        self.is_approximate_computing_enabled = self.config.getboolean(conf.SEC_SIM, conf.ENABLE_APPROXIMATE_COMPUTING, fallback=False)

        # Seeds
        n_arrival_processes = sum([len(arrival_procs) for arrival_procs in self.node2arrivals.values()])
        # Spawn off child SeedSequences to pass to child processes.
        child_seeds = self.seed_sequence.spawn(9 + 3 * n_arrival_processes)
        self.service_rng = default_rng(child_seeds[0])
        self.node_choice_rng = default_rng(child_seeds[1])
        self.policy_rng1 = default_rng(child_seeds[2])
        self.keys_rng = default_rng(child_seeds[3])
        self.keys_policy_rng = default_rng(child_seeds[4])

        self.cloud_region_choice = default_rng(child_seeds[5])
        self.cloud_node_random_choice = default_rng(child_seeds[6])
        self.rng_variant = default_rng(child_seeds[7])
        self.latency_rng = default_rng(child_seeds[8])

        i = 8
        for n, arvs in self.node2arrivals.items():
            for arv in arvs:
                arv.init_rng(default_rng(child_seeds[i]), default_rng(child_seeds[i + 1]),
                             default_rng(child_seeds[i + 2]))
                i += 3

        self.max_neighbors = self.config.getint(conf.SEC_SIM, conf.EDGE_NEIGHBORS, fallback=2)
        self.max_edge_neighbors_per_region = self.config.getint(conf.SEC_CARBON, conf.EDGE_NEIGHBORS, fallback=2)

        # Other params
        self.init_time = {}
        avg_regional_init_time = {}

        # Calculate average speedup for cloud regions
        for region in self.infra.regions:
            if region.is_cloud():
                avg_speedup = 0
                cloud_nodes = self.infra.get_cloud_nodes_by_region(region)
                if len(cloud_nodes) > 0:
                    for node in cloud_nodes:
                        avg_speedup = avg_speedup + node.speedup
                    avg_speedup = avg_speedup / len(cloud_nodes)
                    avg_regional_init_time[region] = avg_speedup

        for node in self.infra.get_nodes(ignore_non_processing=False):
            if node.speedup > 0:
                if isinstance(node,Dispatcher):
                    # Use average regional initialization time for dispatcher nodes in cloud regions
                    speedup = avg_regional_init_time[node.region]
                else:
                    speedup = node.speedup
                for fun in self.functions:
                        self.init_time[(fun, node)] = fun.initMean / speedup



    def new_policy(self, configured_policy, node):
        if configured_policy == "basic":
            return policy.BasicPolicy(self, node)
        if configured_policy == "basic-multi-region":
            return policy.BasicPolicyMultiRegion(self, node)
        if configured_policy == "basic-budget":
            return policy.BasicBudgetAwarePolicy(self, node)
        if configured_policy == "basic-edge":
            return policy.BasicEdgePolicy(self, node)
        if configured_policy == "cloud":
            return policy.CloudPolicy(self, node)
        if configured_policy == "greedy-multi-region": #latency
            return policy.GreedyPolicyMultiRegion(self, node)
        if configured_policy == "greedy-carbon-aware":
            return policy.GreedyCarbonAware(self, node)
        if configured_policy == "greedy-carbon-aware-strict":
            return policy.GreedyCarbonAwareStrict(self, node)
        elif configured_policy == "probabilistic-legacy":
            self.config.set(conf.SEC_POLICY, conf.EDGE_OFFLOADING_ENABLED, "false")
            return probabilistic.ProbabilisticPolicy(self, node)
        elif configured_policy == "probabilistic-legacy-strict":
            self.config.set(conf.SEC_POLICY, conf.EDGE_OFFLOADING_ENABLED, "false")
            return probabilistic.ProbabilisticPolicy(self, node, True)
        elif configured_policy == "probabilistic":
            return probabilistic.ProbabilisticPolicy(self, node)
        elif configured_policy == "probabilistic-strict":
            return probabilistic.ProbabilisticPolicy(self, node, True)
        elif configured_policy == "probabilistic-strictAlt" or configured_policy == "fgcs24":
            self.config.set(conf.SEC_POLICY, conf.MULTIPLE_OFFLOADING_ALLOWED, "false")
            return probabilistic.ProbabilisticPolicy(self, node, True)
        elif configured_policy == "probabilistic-offline":
            return probabilistic.OfflineProbabilisticPolicy(self, node)
        elif configured_policy == "probabilistic-offline-strict":
            return probabilistic.OfflineProbabilisticPolicy(self, node, True)
        elif configured_policy == "greedy":
            return policy.GreedyPolicy(self, node)
        elif configured_policy == "greedy-budget":
            return policy.GreedyBudgetAware(self, node)
        elif configured_policy == "greedy-min-cost":
            return policy.GreedyPolicyWithCostMinimization(self, node)
        elif configured_policy == "random":
            return probabilistic.RandomPolicy(self, node)
        elif configured_policy == "random-multi-region":
            return probabilistic_carbon_aware.RandomPolicy(self, node)
        elif configured_policy == "random-multi-region-no-drop":
            return probabilistic_carbon_aware.RandomPolicyNoDrop(self, node)
        elif configured_policy == "random-stateful":
            return stateful.RandomStatefulOffloadingPolicy(self, node)
        elif configured_policy == "state-aware":
            return stateful.StateAwareOffloadingPolicy(self, node)
        elif configured_policy == "state-aware-always-offload":
            return stateful.AlwaysOffloadStatefulPolicy(self, node)
        elif configured_policy == "probabilistic-carbon-aware":
            return probabilistic_carbon_aware.ProbabilisticCarbonAwarePolicy(self, node,True)
        elif configured_policy == "dispatcher-policy":
            return policy.CloudRegionDispatcherPolicy(self, node)
        elif configured_policy == "random":
            return probabilistic.RandomPolicy(self, node)
        else:
            raise RuntimeError(f"Unknown policy: {configured_policy}")

    def new_state_migration_policy(self, stateful_policy_name: str):
        if stateful_policy_name == "none":
            return None
        elif stateful_policy_name == "random":
            return stateful.RandomKeyMigrationPolicy(self, self.keys_policy_rng)
        elif stateful_policy_name == "gradient-discent":
            return stateful.GradientBasedMigrationPolicy(self, self.keys_policy_rng)
        elif stateful_policy_name == "spring-based":
            return stateful.SpringBasedMigrationPolicy(self, self.keys_policy_rng)
        elif stateful_policy_name == "greedy":
            return stateful.SimpleGreedyMigrationPolicy(self, self.keys_policy_rng)
        elif stateful_policy_name == "ilp-min-access":
            return stateful.ILPMinDataAccessTimeMigrationPolicy(self, self.keys_policy_rng)
        elif stateful_policy_name == "ilp":
            return stateful.ILPBoundedDataAccessTimeMigrationPolicy(self, self.keys_policy_rng)
        else:
            raise RuntimeError(f"Unknown state migration policy: {stateful_policy_name}")

    def run(self):
        # Simulate
        self.close_the_door_time = self.config.getfloat(conf.SEC_SIM, conf.CLOSE_DOOR_TIME, fallback=100)
        self.events = []
        self.t = 0.0
        self.node2policy = {}
        self.rows_to_write_update_co2 = []

        self.expiration_timeout = self.config.getfloat(conf.SEC_CONTAINER, conf.EXPIRATION_TIMEOUT, fallback=600)

        add_enum_members(SchedulerDecision, self.infra.regions)
        self.of_alpha = self.config.getfloat(conf.SEC_POLICY, conf.ALPHA, fallback=0.0)
        self.of_beta = self.config.getfloat(conf.SEC_POLICY, conf.BETA, fallback=0.0)
        self.is_co2_trace_over = {node: False for node in self.infra.get_nodes(ignore_non_processing=False)}

        self.initialize_co2_emissions()
        for n in (self.infra.get_nodes(ignore_non_processing=False)):
            self.read_co2_intensity(n, self.is_co2_trace_over)

        # Policy
        policy_name = self.config.get(conf.SEC_POLICY, conf.POLICY_NAME, fallback="basic")
        for n in self.infra.dispatchers:
            _policy = n.custom_sched_policy if n.custom_sched_policy is not None else "dispatcher-policy"
            self.node2policy[n] = self.new_policy(_policy, n)
        for n in self.infra.edge_nodes:
            _policy = n.custom_sched_policy if n.custom_sched_policy is not None else policy_name
            self.node2policy[n] = self.new_policy(_policy, n)
        for n in self.infra.cloud_nodes:
            _policy = n.custom_sched_policy if n.custom_sched_policy is not None else "cloud"
            self.node2policy[n] = self.new_policy(_policy, n)


        self.key_migration_policy = None
        stateful_policy_name = self.config.get(conf.SEC_STATEFUL, conf.POLICY_NAME, fallback="none")
        self.key_migration_policy = self.new_state_migration_policy(stateful_policy_name)


        self.policy_update_interval = self.config.getfloat(conf.SEC_POLICY, conf.POLICY_UPDATE_INTERVAL, fallback=-1)
        self.rate_update_interval = self.config.getfloat(conf.SEC_SIM, conf.RATE_UPDATE_INTERVAL, fallback=-1)
        self.stats_print_interval = self.config.getfloat(conf.SEC_SIM, conf.STAT_PRINT_INTERVAL, fallback=-1)

        self.carbon_intensity_update_interval = self.config.getfloat(conf.SEC_CARBON, conf.CARBON_INTENSITY_UPDATE_INTERVAL, fallback=-1)
        self.policy_dispatcher_update_interval = self.config.getfloat(conf.DISPATCHER, conf.POLICY_UPDATE_INTERVAL, fallback=-1)

        self.utilization_update_interval = self.config.getfloat(conf.SEC_CONTAINER, conf.UTILIZATION_UPDATE_INTERVAL, fallback=5)
        self.latency_update_interval = self.config.getfloat(conf.SEC_CARBON, conf.LATENCY_UPDATE_INTERVAL, fallback=-1)
        self.latency_dev_st = self.config.getfloat(conf.SEC_CARBON, conf.LATENCY_DEV_ST, fallback=0.1)
        self.latency_cap = self.config.getfloat(conf.SEC_CARBON, conf.LATENCY_CAP, fallback=0.0)

        self.instant_utilization_tmp_dict = {n: deque(maxlen=1000) for n in self.infra.get_nodes()}
        self.lp_utilization_tmp_dict = {n: deque(maxlen=1000) for n in self.infra.get_nodes()}

        self.instant_energy_tmp_dict = {n: deque(maxlen=1000) for n in self.infra.get_nodes()}
        self.lp_energy_tmp_dict = {n: deque(maxlen=1000) for n in self.infra.get_nodes()}

        self.stats_file = sys.stdout

        self.count_policy_update = 0
        self.count_carbon_intensity_update = 0

        rt_print_filename = self.config.get(conf.SEC_SIM, conf.RESP_TIMES_FILE, fallback="")

        if len(rt_print_filename) > 0:
            self.resp_times_file = open(rt_print_filename, "w")
            print(f"Function,Class,Node,Offloaded,Cold,DataAccess,RT", file=self.resp_times_file)
        else:
            self.resp_times_file = None

        if not self.config.getboolean(conf.SEC_SIM, conf.PLOT_RESP_TIMES, fallback=False):
            self.resp_time_samples = {}
        else:
            self.resp_time_samples = {(f, c): [] for f in self.functions for c in f.get_invoking_classes()}

        for n, arvs in self.node2arrivals.copy().items():
            for arv in arvs:
                self.__schedule_next_arrival(n, arv)

        if len(self.events) == 0:
            # No arrivals
            print("No arrivals configured.")
            exit(1)

        # Initialize state placement
        stateful.init_key_placement(self.functions, self.infra, self.keys_rng)

        if self.policy_update_interval > 0.0:
            self.schedule(self.policy_update_interval, PolicyUpdate())
        if self.rate_update_interval > 0.0:
            self.schedule(self.rate_update_interval, ArrivalRateUpdate())
        if self.stats_print_interval > 0.0:
            self.schedule(self.stats_print_interval, StatPrinter())
            stats_print_filename = self.config.get(conf.SEC_SIM, conf.STAT_PRINT_FILE, fallback="")
            if len(stats_print_filename) > 0:
                self.stats_file = open(stats_print_filename, "w")

        if self.carbon_intensity_update_interval > 0.0:
            self.count_carbon_intensity_update = self.count_carbon_intensity_update+1
            self.schedule(self.carbon_intensity_update_interval, CarbonIntensityUpdate())
        if self.policy_dispatcher_update_interval > 0.0:    #for cloud nodes status update
            self.schedule(self.policy_dispatcher_update_interval, DispatcherUpdate())
        if self.utilization_update_interval > 0.0:
            self.schedule(self.utilization_update_interval, NodeUtilizationUpdate())
        if self.latency_update_interval > 0.0:
            self.schedule(self.latency_update_interval, LatencyUpdate())

        while len(self.events) > 0:
            t, e = heappop(self.events)
            self.handle(t, e)

        if self.stats_print_interval > 0:
            self.print_periodic_stats()
            print("]", file=self.stats_file)
            if self.stats_file != sys.stdout:
                self.stats_file.close()
                self.stats.print(sys.stdout)
        elif self.config.getboolean(conf.SEC_SIM, conf.PRINT_FINAL_STATS, fallback=True):
            self.stats.print(sys.stdout)
        else:
            print(self.stats.utility - self.stats.penalty)

        if self.resp_times_file is not None:
            self.resp_times_file.close()

        if len(self.resp_time_samples) > 0:
            plot.plot_rt_cdf(self.resp_time_samples)

        for n, arvs in self.node2arrivals.items():
            for arv in arvs:
                arv.close()

        return self.stats

    def move_key(self, k, src_node, dest_node):
        if src_node == dest_node:
            return
        dest_node.kv_store[k] = src_node.kv_store[k]
        del (src_node.kv_store[k])
        key_locator.update_key_location(k, dest_node)

        moved_bytes = dest_node.kv_store[k]
        self.stats.data_migrations_count += 1
        self.stats.data_migrated_bytes += moved_bytes

    def __schedule_next_arrival(self, node, arrival_proc):
        if not self.external_arrivals_allowed:
            return

        c = arrival_proc.next_class()
        iat = arrival_proc.next_iat()
        f = arrival_proc.function

        if iat >= 0.0 and self.t + iat < self.close_the_door_time and not self.is_co2_trace_over[node]:
            self.schedule(self.t + iat, Arrival(node, f, c, arrival_proc))
        else:
            # Close the arrival process if scheduling is not possible
            arrival_proc.close()
            self.node2arrivals[node].remove(arrival_proc)
            if not self.node2arrivals[node]:  # Remove the node if no arrivals are left
                del self.node2arrivals[node]

        # Check if all arrivals are done, then clean up events
        if not self.node2arrivals:
            for _, event in self.events:
                if isinstance(event, (CheckExpiredContainers, PolicyUpdate, CarbonIntensityUpdate,
                                      DispatcherUpdate, ArrivalRateUpdate, StatPrinter, NodeUtilizationUpdate, LatencyUpdate)):
                    event.canceled = True
            self.external_arrivals_allowed = False

    def schedule(self, t, event):
        heappush(self.events, (t, event))

    def print_periodic_stats(self):
        of = self.stats_file if self.stats_file is not None else sys.stdout
        if not self.first_stat_print:
            print(",", end='', file=of)
        else:
            print("[", file=of)
        self.stats.print(of)
        self.first_stat_print = False



    def handle(self, t, event):
        if event.canceled:
            return
        self.t = t
        #print(event)

        self.__event_counter += 1
        if self.__event_counter % 10000 == 0:
            #print(t)
            self.__event_counter = 0
        if isinstance(event, Arrival):
            self.handle_arrival(event)
        elif isinstance(event, Completion):
            self.handle_completion(event)
        elif isinstance(event, PolicyUpdate):
            for n, p in self.node2policy.items():
                upd_t0 = time.time()
                #print("node co2: "+n.co2_footprint)
                p.update()
                self.stats.update_policy_upd_time(n, time.time() - upd_t0)

                '''
                if not isinstance(n, Dispatcher):
                    
                                       #todo: poi TOGLIERE
                    # --- window-average instant utilization (same window as policy update) ---
                    k = max(1, int(round(self.policy_update_interval / self.utilization_update_interval)))

                    if len(n.utilization_list) > 0:
                        tail = list(n.utilization_list)[-k:]
                        inst_u = sum(tail) / len(tail)
                    else:
                        inst_u = 0.0

                    # LP memory utilization (after your optimizer fix above)
                    if len(self.lp_utilization_tmp_dict[n]) > 0:
                        lp_u = self.lp_utilization_tmp_dict[n][-1]
                    else:
                        lp_u = None

                    print(f"[t={self.t:8.2f}] node={n}  inst_u={inst_u:.4f}  lp_u={lp_u if lp_u is not None else 'NA'}")
                '''


            # Migrate keys
            if self.key_migration_policy is not None:
                upd_t0 = time.time()
                self.key_migration_policy.update_metrics()
                self.key_migration_policy.migrate()
                for p in self.node2policy.values():
                    if isinstance(p, stateful.StateAwareOffloadingPolicy):
                        p.latency_estimation_cache = {}
                self.stats.update_mig_policy_upd_time(time.time() - upd_t0)


            self.schedule(t + self.policy_update_interval, event)
            self.count_policy_update = self.count_policy_update+1
            #print("count_policy_update: ", self.count_policy_update,
            #      "t = ",t,
            #      " scheduled t = ",t + self.policy_update_interval)
        elif isinstance(event, CarbonIntensityUpdate):
            for n in self.node2policy:
                if not self.is_co2_trace_over[n]:
                    self.read_co2_intensity(n, self.is_co2_trace_over)
            self.schedule(t + self.carbon_intensity_update_interval, event)
            self.count_carbon_intensity_update = self.count_carbon_intensity_update+1
            #print("count_carbon_intensity_update: ", self.count_carbon_intensity_update,
            #      "t = ", t,
            #      " scheduled t = ", t + self.carbon_intensity_update_interval)
        elif isinstance(event, DispatcherUpdate):
            for n, p in self.node2policy.items():
                if isinstance(n, Dispatcher):
                    upd_t0 = time.time()
                    p.update()
                    self.stats.update_policy_upd_time(n, time.time() - upd_t0)
            self.schedule(t + self.policy_dispatcher_update_interval, event)
        elif isinstance(event, ArrivalRateUpdate):
            for n, arvs in self.node2arrivals.copy().items():
                for arv in arvs:
                    if arv.has_dynamic_rate():
                        arv.update_dynamic_rate()
            self.schedule(t + self.rate_update_interval, event)
        elif isinstance(event, StatPrinter):
            self.print_periodic_stats()
            self.schedule(t + self.stats_print_interval, event)
        elif isinstance(event, CheckExpiredContainers):
            if len(event.node.warm_pool) == 0:
                return
            f, timeout = event.node.warm_pool.front()
            if timeout < t:
                self.stats.update_memory_usage(event.node, self.t)
                event.node.curr_memory += f.memory
                event.node.warm_pool.pool = event.node.warm_pool.pool[1:]
        elif isinstance(event, NodeUtilizationUpdate):
            for n in self.node2policy:
                if not isinstance(n, Dispatcher):
                    total_occupied_memory = n.total_memory - n.curr_memory  #TODO: QUI!
                    warm_containers_memory = sum([entry[0].memory for entry in n.warm_pool.pool])
                    instant_utilization = (total_occupied_memory - warm_containers_memory) / n.total_memory
                    instant_utilization = max(0.0, min(1.0, instant_utilization))
                    #n.add_utilization(instant_utilization)
                    #self.stats.node2utilization[n].append(instant_utilization)

                    #E = P * T [ J = W * sec ]
                    #gCO2(t) = (Pmax - Pidle)*instant_utilization*utilization_update_interval*(1/KWH)*node_co2_intensity
                    P = n.processing_power_consumption - n.idle_power_consumption
                    I = n.co2_footprint.co2_intensity

                    emitted_gCO2_interval_by_node = P * instant_utilization * self.utilization_update_interval * (1/KWH) * I # Pidle * I + P_running * u * I
                    self.stats.co2_emission_per_node[n] += emitted_gCO2_interval_by_node
                    self.stats.co2_emission_total += emitted_gCO2_interval_by_node
                    self.stats.co2_emission_computation += emitted_gCO2_interval_by_node

            self.schedule(t + self.utilization_update_interval, event)
        elif isinstance(event, LatencyUpdate):
            self.update_latencies_abs_gaussian(self.latency_dev_st, self.latency_cap)
            #print("latencies: ",self.infra.latency.items())
            self.schedule(t + self.latency_update_interval, event)
        else:
            raise RuntimeError("")

    def handle_completion(self, event):
        f = event.function
        c = event.qos_class
        n = event.node

        rt = self.t - event.arrival

        duration = event.exec_time
        dat = event.data_access_time
        #print(f"Completed {f}-{c}: {rt}")

        assert not isinstance(n, Dispatcher)
        # Account for the time needed to send back the result

        function_transmission_energy = 0.0
        I = 0.0

        if event.offloaded_from != None and len(event.offloaded_from) > 0:
            curr_node = n
            for remote_node in reversed(event.offloaded_from):
                rt += self.infra.get_latency(curr_node, remote_node)
                curr_node = remote_node
            if n.region.is_cloud():
                #cloud node
                assert len(event.offloaded_from) == 2
                initial_node = event.offloaded_from[0]
                dispatcher = event.offloaded_from[1]
                #energy for function processing on cloud node + offloading from local node to dispatcher
                function_co2_emission = compute_cloud_emissions(f, dispatcher, duration, n, initial_node)
                function_transmission_energy = compute_transmission_energy_cloud(f,dispatcher, initial_node, n)

                I = dispatcher.co2_footprint.co2_intensity

            else:
                #edge node
                assert len(event.offloaded_from) == 1
                initial_node = event.offloaded_from[0]
                function_co2_emission = compute_edge_emissions(f, n.curr_memory, n.processing_power_consumption,
                                                               n.idle_power_consumption,
                                                               duration, initial_node.tx_power_consumption,
                                                               n.rx_power_consumption,
                                                               initial_node.rx_power_consumption,
                                                               n.tx_power_consumption,
                                                               n.co2_footprint.co2_intensity)

                function_transmission_energy = compute_transmission_energy_edge(f,
                                                                                initial_node.tx_power_consumption,
                                                                                initial_node.rx_power_consumption,
                                                                                n.tx_power_consumption,
                                                                                n.rx_power_consumption)
                I = n.co2_footprint.co2_intensity

        else:
            function_co2_emission = compute_local_emissions(f, n, duration)

        function_transmission_co2_emission = function_transmission_energy * (1 / KWH) * I

        self.stats.co2_emission_totalOld += function_co2_emission

        self.stats.co2_emission_total += function_transmission_co2_emission
        self.stats.co2_emission_per_node[n] += function_transmission_co2_emission
        self.stats.co2_emission_transmission += function_transmission_co2_emission

        #u_f = n.utilization_during_function_execution(duration)
        #self.instant_utilization_tmp_dict[n].append(u_f)
        #self.instant_energy_tmp_dict[n].append(function_co2_emission)

        self.stats.resp_time_sum[(f, c, n)] += rt
        if (f, c, n) in self.resp_time_samples:
            self.resp_time_samples[(f, c, n)].append(rt)
        self.stats.completions[(f, c, n)] += 1
        self.stats.execution_time_sum[(f, n)] += duration
        self.stats.node2completions[(f, n)] += 1
        variant_utility = 1.0
        if not f.is_default:
            for v in self.variants:
                if v.name == f.name:
                    variant_utility = v.utility
                    break

        self.stats.raw_utility += c.utility * variant_utility
        if c.max_rt <= 0.0 or rt <= c.max_rt:
            self.stats.utility += c.utility * variant_utility
            self.stats.utility_detail[(f, c, n)] += c.utility * variant_utility

        elif c.max_rt > 0.0:
            self.stats.violations[(f, c, n)] += 1
            self.stats.penalty += c.deadline_penalty

        if f.max_data_access_time is not None and dat > f.max_data_access_time:
            self.stats.data_access_violations[f] += 1
            self.stats.data_access_tardiness += dat - f.max_data_access_time

        if n.cost > 0.0:
            self.stats.cost += duration * f.memory / 1024 * n.cost

        if self.resp_times_file is not None:
            print(
                f"{f},{c},{n},{event.offloaded_from != None and len(event.offloaded_from) > 0},{event.cold},{dat},{rt}",
                file=self.resp_times_file)

        n.warm_pool.append((f, self.t + self.expiration_timeout))
        if self.external_arrivals_allowed:
            self.schedule(self.t + self.expiration_timeout, CheckExpiredContainers(n))

        region = n.region
        self.stats.total_processing_time = self.t
        self.stats.emission_intensity = self.stats.co2_emission_total / self.stats.total_processing_time
        if region.is_cloud() and not isinstance(n, Dispatcher):
            self.stats.execution_time_sum_cloud_nodes[(region, f, n)] += duration
            self.stats.completions_cloud_nodes[(region, f, n)] += 1



    def do_offload(self, arrival, target_node):

        latency = self.infra.get_latency(arrival.node, target_node)
        transfer_time = arrival.function.inputSizeMean * 8 / 1000 / 1000 / self.infra.get_bandwidth(arrival.node,
                                                                                                    target_node)
        remote_arv = Arrival(target_node, arrival.function, arrival.qos_class,
                             offloaded_from=arrival.offloaded_from.copy())

        if arrival.offloaded_from is None or len(arrival.offloaded_from) == 0: #first offload
            remote_arv.original_arrival_time = self.t
        else:
            remote_arv.original_arrival_time = arrival.original_arrival_time

        remote_arv.offloaded_from.append(arrival.node)

        self.schedule(self.t + latency + OFFLOADING_OVERHEAD + transfer_time, remote_arv)

    def handle_arrival(self, event):
        n = event.node
        node_policy = self.node2policy[n]
        external = len(event.offloaded_from) == 0
        arv_proc = event.arrival_proc
        f = event.function
        c = event.qos_class
        self.stats.arrivals[(f, c, n)] += 1
        if external:
            self.stats.ext_arrivals[(f, c, n)] += 1

        # Policy
        sched_decision, target_node = node_policy.schedule(f, c, event.offloaded_from)

        if sched_decision == SchedulerDecision.EXEC_VAR:

            assert n.region.is_cloud() == False
            #assert len(event.offloaded_from) == 0

            f = f.active_variant

            duration, data_access_time = self.next_function_duration(f, n)
            # check warm or cold
            if f in n.warm_pool:
                n.warm_pool.remove(f)
                init_time = 0
            else:
                self.stats.update_memory_usage(event.node, self.t)
                if n.curr_memory >= f.memory:
                    assert (n.curr_memory >= f.memory)
                n.curr_memory -= f.memory
                self.stats.cold_starts[(f, n)] += 1

                init_time = self.init_time[(f, n)]


            arrival_time = self.t if event.original_arrival_time is None else event.original_arrival_time
            self.schedule(float(self.t + init_time + duration),
                          Completion(arrival_time, f, c, n, init_time > 0, duration, None,
                                     data_access_time))

        elif sched_decision == SchedulerDecision.EXEC:

            duration, data_access_time = self.next_function_duration(f, n)
            region = n.region

            # check warm or cold
            if f in n.warm_pool:
                n.warm_pool.remove(f)
                init_time = 0
            else:
                self.stats.update_memory_usage(event.node, self.t)
                if n.curr_memory >= f.memory:
                    assert (n.curr_memory >= f.memory)
                n.curr_memory -= f.memory
                self.stats.cold_starts[(f, n)] += 1

                # if node is a cloud processing node, update stats (exec time & num completions)
                if region.is_cloud() and not isinstance(n, Dispatcher):
                    self.stats.cold_starts_cloud_nodes[(region, f, n)] += 1

                init_time = self.init_time[(f, n)]
            #if f.name == "f3" and c.name == "critical" and n.region.name == "edge_zone_1":
            #and len(event.offloaded_from)>0:
                #print("ciao")
            arrival_time = self.t if event.original_arrival_time is None else event.original_arrival_time
            self.schedule(float(self.t + init_time + duration),
                          Completion(arrival_time, f, c, n, init_time > 0, duration, event.offloaded_from,
                                     data_access_time))

        elif sched_decision == SchedulerDecision.DROP:
            self.stats.dropped_reqs[(f, c, n)] += 1
            self.stats.penalty += c.drop_penalty
            if event.offloaded_from is not None and len(event.offloaded_from) > 0:
                self.stats.dropped_offloaded[(f, c, n)] += 1

        elif sched_decision == SchedulerDecision.OFFLOAD_EDGE:
            #assert f.is_default == True
            if target_node is not None:
                remote_node = target_node
            else:
                remote_node = node_policy.pick_edge_node(f, c)
            if remote_node is None:
                # drop
                self.stats.dropped_reqs[(f, c, n)] += 1
                print("edge - self.stats.dropped_reqs[(f, c, n)] += 1")
                self.stats.penalty += c.drop_penalty
            else:
                self.stats.offloaded[(f, c, n)] += 1
                self.do_offload(event, remote_node)
        else:   #OFFLOAD_CLOUD
            assert f.is_default == True
            if target_node is not None:
                remote_node = target_node
            else:
                region_name = self.get_region_name_by_scheduler_decision(sched_decision)
                remote_node = self.pick_cloud_remote_node_by_region(region_name)

            if remote_node is None:
                # drop
                self.stats.dropped_reqs[(f, c, n)] += 1
                print("cloud - self.stats.dropped_reqs[(f, c, n)] += 1")

                self.stats.penalty += c.drop_penalty
            else:
                self.stats.offloaded[(f, c, n)] += 1
                self.do_offload(event, remote_node)

        # Schedule next (if this is an external arrival)
        if external:
            self.__schedule_next_arrival(n, arv_proc)

    def get_region_name_by_scheduler_decision(self, sched_decision):
        return sched_decision.name[len(conf.OFFLOAD_CLOUD_DECISION):].lower()

    def pick_cloud_remote_node_by_region(self, region_name):
        #region_name = sched_decision.name[len(conf.OFFLOAD_CLOUD_DECISION):].lower()
        for dispatcher in self.infra.dispatchers:
            if dispatcher.region.name == region_name:
                return dispatcher

    def next_function_duration(self, f: Function, n: Node):
        # execution time
        duration = float(self.service_rng.gamma(1.0 / f.serviceSCV, f.serviceMean * f.serviceSCV / n.speedup))
        data_access_time = 0
        # we add the time to access state
        for k, prob in f.accessed_keys:
            # check if it is accessed
            if self.keys_rng.random() <= prob:
                # check if the key is on the node
                if k not in n.kv_store:
                    remote_node = stateful.key_locator.get_node(k)
                    assert (k in remote_node.kv_store)
                    value_size = remote_node.kv_store[k]
                    extra_latency = self.infra.get_latency(n, remote_node) * 2
                    # bandwidth
                    extra_latency += value_size / (self.infra.get_bandwidth(n, remote_node) * 125000)
                    data_access_time += extra_latency
                self.stats.data_access_count[(k, f, n)] += 1
        return float(duration + data_access_time), float(data_access_time)

    def pick_closest_cloud_region(self, n: Node):
        nodes_w_lat = [(_n, self.infra.get_latency(n, _n)) for _n in self.infra.dispatchers]
        if len(nodes_w_lat) < 1:
            remote_node = None
            scheduler_decision = SchedulerDecision.DROP
        else:
            remote_node = sorted(nodes_w_lat, key=lambda x: x[1])[0][0]
            region = remote_node.region
            scheduler_decision = None
            possible_decisions = list(SchedulerDecision)
            for dec in possible_decisions:
                if region.name.upper() in dec.name:
                    scheduler_decision = dec
                    break
        return scheduler_decision, remote_node



    def read_co2_intensity(self, node, is_co2_trace_over):
        n = node.co2_footprint.count
        nth_row = node.region.datetime_co2intensity.iloc[n]
        #if n <= len(node.region.datetime_co2intensity) - 1:
        if nth_row[conf.CO2_TRACES_COL_TIMESTAMP] <= self.end_date_co2_emissions:

            nth_row = node.region.datetime_co2intensity.iloc[n]
            # print("nth row: ", nth_row)
            node.co2_footprint.co2_datetime = nth_row[conf.CO2_TRACES_COL_TIMESTAMP]
            node.co2_footprint.co2_intensity = nth_row[conf.CO2_TRACES_COL_INTENSITY_DIRECT]
            node.co2_footprint.count = n + 1


        else:
            is_co2_trace_over[node] = True
            print("df finito! n=", node, " data: ",
                  node.region.datetime_co2intensity.iloc[n - 1][conf.CO2_TRACES_COL_TIMESTAMP])

    def initialize_co2_emissions(self):
        for node in chain(self.infra.edge_nodes, self.infra.cloud_nodes):
            for function in self.functions:
                if function not in node.g_co2_emissions:
                    node.g_co2_emissions[function] = {}
                for decision in list(SchedulerDecision):
                    node.g_co2_emissions[function][decision] = 0.0

    def update_latencies_abs_gaussian(self, sigma_sec, cap_extra_sec):
        self.infra.latency.update(self.infra.base_latency)

        edges = [n for n in self.infra.regions if not n.is_cloud()]
        clouds = [n for n in self.infra.regions if n.is_cloud()]

        loc = 0.0
        scale = float(sigma_sec)
        a = (0.0 - loc) / scale
        b = (float(cap_extra_sec) - loc) / scale

        for e in edges:
            for c in clouds:
                mu = self.infra.get_base_latency(e, c)

                #x = float(self.latency_rng.normal(loc=0.0, scale=sigma_sec))

                #extra = abs(x)
                #if cap_extra_sec and cap_extra_sec > 0.0: #todo trunc normal
                #    extra = min(extra, cap_extra_sec)

                extra = float(truncnorm.rvs(a, b, loc=0.0, scale=scale,
                            random_state=self.latency_rng))

                self.infra.latency[(e, c)] = mu + extra
                self.infra.latency[(c, e)] = mu + extra

from scipy.stats import truncnorm

