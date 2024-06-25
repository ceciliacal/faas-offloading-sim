from optimization import OptProblemParams
from probabilistic import ProbabilisticPolicy
import conf
import lp_optimizer_energy_aware

class ProbabilisticEnergyAwarePolicy(ProbabilisticPolicy):

    def update(self):
        super().update_metrics()

        arrivals = sum(
            [self.arrival_rates.get((f, c), 0.0) for f in self.simulation.functions for c in self.simulation.classes])
        if arrivals > 0.0:
            # trigger the optimizer
            self.update_probabilities()

        self.stats_snapshot = self.simulation.stats.to_dict()
        self.last_update_time = self.simulation.t

        # reset counters
        self.curr_local_blocked_reqs = 0
        self.curr_local_reqs = 0

    def update_probabilities(self):
        if self.adaptive_local_memory:
            loss = self.curr_local_blocked_reqs/self.curr_local_reqs if self.curr_local_reqs > 0 else 0
            if loss > 0.0:
                self.local_usable_memory_coeff -= self.local_usable_memory_coeff*loss/2.0
            else:
                self.local_usable_memory_coeff = min(self.local_usable_memory_coeff*1.1, 1.0)
            print(f"{self.node}: Usable memory: {self.local_usable_memory_coeff:.2f}")


        if not self.edge_enabled:
            # probably redundant, just to be sure
            self.aggregated_edge_memory = 0

        params = OptProblemParams(self.node,
                self.cloud,
                self.simulation.functions,
                self.simulation.classes,
                self.arrival_rates,
                self.estimated_service_time,
                self.estimated_service_time_cloud,
                self.init_time_local,
                self.init_time_cloud,
                self.cold_start_prob_local,
                self.cold_start_prob_cloud,
                self.cloud_rtt,
                self.cloud_bw,
                self.local_usable_memory_coeff,
                self.local_budget,
                self.aggregated_edge_memory,
                self.estimated_service_time_edge,
                self.edge_rtt,
                self.cold_start_prob_edge,
                self.init_time_edge,
                self.edge_bw)

        opt = self.get_optimizer()
        new_probs = opt.update_probabilities(params, self.simulation.verbosity)

        if new_probs is not None:
            self.probs = new_probs

    def get_optimizer (self):
        optimizer_to_use =  self.simulation.config.get(conf.SEC_POLICY, conf.QOS_OPTIMIZER, fallback="")
        if optimizer_to_use == "" or optimizer_to_use == "fgcs24" or optimizer_to_use == "lp":
            opt = lp_optimizer_energy_aware
        else:
            raise RuntimeError(f"Unknown optimizer: {optimizer_to_use}")
        return opt

