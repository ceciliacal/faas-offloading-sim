import math
import sys


import numpy as np
import pandas as pd
import yaml
from numpy.random import SeedSequence

import co2_footprint
import faas
from arrivals import PoissonArrivalProcess, TraceArrivalProcess, MAPArrivalProcess
from faas import Variant
from infrastructure import *
from simulation import Simulation


def read_spec_file(spec_file_name, infra, config):
    peer_exposed_memory_fraction = config.getfloat(conf.SEC_SIM, conf.EDGE_EXPOSED_FRACTION, fallback=0.5)
    utilization_update_interval = config.getfloat(conf.SEC_CONTAINER, conf.UTILIZATION_UPDATE_INTERVAL,
                                                            fallback=5)

    with open(spec_file_name, "r") as stream:
        spec = yaml.safe_load(stream)

        classname2class = {}
        classes = []
        for c in spec["classes"]:
            classname = c["name"]
            arrival_weight = c.get("arrival_weight", 1.0)
            utility = c.get("utility", 1.0)
            penalty = c.get("penalty", 0.0)
            if penalty > 0.0:
                print("[WARNING] Using the deprecated 'penalty' attribute")
                deadline_penalty = penalty
                drop_penalty = 0.0
            else:
                deadline_penalty = c.get("deadline_penalty", 0.0)
                drop_penalty = c.get("drop_penalty", 0.0)
            deadline = c.get("max_resp_time", 1.0)
            newclass = faas.QoSClass(classname, deadline, arrival_weight, utility=utility,
                                     deadline_penalty=deadline_penalty, drop_penalty=drop_penalty)
            classes.append(newclass)
            classname2class[classname] = newclass

        node_names = {}
        nodes = spec["nodes"]
        for n in nodes:
            node_name = n["name"]
            reg_name = n["region"]
            reg = infra.get_region(reg_name)
            memory = n["memory"] if "memory" in n else 1024
            speedup = n["speedup"] if "speedup" in n else 1.0
            cost = n["cost"] if "cost" in n else 0.0
            custom_policy = n["policy"] if "policy" in n else None
            processing_power_consumption = n[
                "processing_power_consumption"] if "processing_power_consumption" in n else 0.0
            idle_power_consumption = n[
                "idle_power_consumption"] if "idle_power_consumption" in n else 0.0
            tx_power_consumption = n["tx_power_consumption"] if "tx_power_consumption" in n else 0.0
            rx_power_consumption = n["rx_power_consumption"] if "rx_power_consumption" in n else 0.0

            # Compute carbon emissions
            carbon_emission = co2_footprint.CO2footprint(node_name)

            # Determine node type
            NodeClass = faas.Dispatcher if conf.DISPATCHER in node_name else faas.Node
            node = NodeClass(node_name, memory, speedup, reg, carbon_emission,
                             processing_power_consumption,
                             idle_power_consumption,
                             tx_power_consumption,
                             rx_power_consumption,
                             utilization_update_interval,
                             cost=cost,
                             custom_sched_policy=custom_policy,
                             peer_exposed_memory_fraction=peer_exposed_memory_fraction)
            # Add node to infrastructure
            node_names[node_name] = node
            infra.add_node(node, reg)
            infra.add_node_by_region_type(node)

        for cloud_node in infra.get_cloud_nodes():
            if not isinstance(cloud_node, faas.Dispatcher):
                cloud_node.has_dispatcher = infra.get_dispatcher_by_region_name(cloud_node.region.name)


        functions = []
        lightest_variants = []

        function_names = {}
        for f in spec["functions"]:
            fname = f["name"]
            memory = f["memory"] if "memory" in f else 128
            duration_mean = f["duration_mean"] if "duration_mean" in f else 1.0
            duration_scv = f["duration_scv"] if "duration_scv" in f else 1.0
            init_mean = f["init_mean"] if "init_mean" in f else 0.500
            input_mean = f["input_mean"] if "input_mean" in f else 1024
            keys_spec = f["keys"] if "keys" in f else []
            max_data_access_time = f["max_data_access_time"] if "max_data_access_time" in f else None
            keys = []
            for ks in keys_spec:
                key = ks["key"]
                p = float(ks.get("probability", "1.0"))
                assert (p <= 1.0)
                assert (p >= 0.0)
                keys.append((key, p))
            output_mean = f["output_mean"] if "output_mean" in f else 256
            # Create variants
            speedups = f.get("speedup", [])
            utilities = f.get("utility", [])
            assert len(speedups) == len(utilities), "Number of Speedup and utility don't match dimension"
            assert 1.0 in speedups, "Speedups must have at least 1 as default speed up"
            speedups_utilities = [Variant(f"{fname}_var_{speedup}", speedup, utility)
                                  for speedup, utility in zip(speedups, utilities) if speedup != 1.0]

            # Initialize the function
            function = faas.Function(
                name=fname, memory=memory, serviceMean=duration_mean, serviceSCV=duration_scv,
                initMean=init_mean, inputSizeMean=input_mean, accessed_keys=keys,
                max_data_access_time=max_data_access_time, outputSizeMean=output_mean,
                variants=speedups_utilities, is_default=True
            )

            function_names[fname] = function
            functions.append(function)
            lightest_variants.extend(speedups_utilities)

        dict_function2variants = process_variants(functions, function_names)

        node2arrivals = {}
        for f in spec["arrivals"]:
            node = node_names[f["node"]]
            fun = function_names[f["function"]]

            if not "classes" in f:
                invoking_classes = classes
            else:
                invoking_classes = [classname2class[qcname] for qcname in f["classes"]]

            if "trace" in f:
                arv = TraceArrivalProcess(fun, invoking_classes, f["trace"])
            elif "rate" in f:
                dynamic_rate_coeff = float(f["dynamic_coeff"]) if "dynamic_coeff" in f else 0.0
                arv = PoissonArrivalProcess(fun, invoking_classes, float(f["rate"]),
                                            dynamic_rate_coeff=dynamic_rate_coeff)
            elif "map" in f:
                # map: 1;2;3;4;...
                matrix_entries = f["map"].split(";")
                n = int(math.sqrt(len(matrix_entries) / 2))
                assert (n * n * 2 == len(matrix_entries))
                D0str = ""
                k = 0
                for i in range(n):
                    for j in range(n):
                        D0str += f"{matrix_entries[k]} "
                        k += 1
                    D0str += ";"
                D1str = ""
                for i in range(n):
                    for j in range(n):
                        D1str += f"{matrix_entries[k]} "
                        k += 1
                    D1str += ";"
                D0 = np.matrix(D0str[:-1])  # strip last semicolon
                D1 = np.matrix(D1str[:-1])
                arv = MAPArrivalProcess(fun, invoking_classes, D0=D0, D1=D1)

            if not node in node2arrivals:
                node2arrivals[node] = []
            node2arrivals[node].append(arv)

    return classes, functions, node2arrivals, dict_function2variants, lightest_variants


#Function variants creation
def process_variants(functions, function_names):
    lightest_functions = []  #type Function
    dict_function2variants = {}

    for function in functions:
        has_function_any_variant = []
        for variant in function.variants:   #Variant
            #if variant.speedup != 1.0:
                lighter_function = faas.Function(
                    name=variant.name, memory=function.memory * variant.speedup,
                    serviceMean= function.serviceMean * variant.speedup,
                    serviceSCV=function.serviceSCV * variant.speedup, initMean=function.initMean,
                    inputSizeMean=function.inputSizeMean, accessed_keys=function.accessed_keys,
                    max_data_access_time=function.max_data_access_time,
                    outputSizeMean=function.outputSizeMean, is_default=False, speedup=variant.speedup
                )
                function_names[lighter_function.name] = lighter_function
                lightest_functions.append(lighter_function)
                variant.self_function = lighter_function
                has_function_any_variant.append(lighter_function)
            #else:
            #   function.active_variant = variant

        function.has_variants = bool(has_function_any_variant)
        #function.variants = [v for v in function.variants]
        dict_function2variants[function] = has_function_any_variant

    functions.extend(lightest_functions)
    return dict_function2variants


def read_traces_file(filename, col_datetime, col_co2intensity, start_date, end_date):

    total_df = pd.read_csv(filename)
    start_date = pd.to_datetime(start_date).date()
    end_date = pd.to_datetime(end_date).date()

    total_df[col_datetime] = pd.to_datetime(total_df[col_datetime])
    weekly_df = total_df[(total_df[col_datetime].dt.date >= start_date) & (total_df[col_datetime].dt.date <= end_date)]
    df = weekly_df[[col_datetime, col_co2intensity]]
    return df


def regions_setup(config):

    col_datetime = conf.CO2_TRACES_COL_TIMESTAMP
    col_co2intensity = conf.CO2_TRACES_COL_INTENSITY_DIRECT
    start_date = config.get(conf.SEC_CARBON, conf.START_DATE, fallback=None)
    end_date = config.get(conf.SEC_CARBON, conf.END_DATE, fallback=None)

    regions_file_path = config.get(conf.SEC_CARBON, conf.REGIONS_FILE, fallback=None)
    with open(regions_file_path, 'r') as file:
        regions_data = yaml.safe_load(file)

    regions = []

    for region in regions_data['regions']:
        co2_traces_filename = region['co2_traces_file']
        co2_dataframe = read_traces_file(region['co2_traces_file'], col_datetime, col_co2intensity, start_date, end_date)

        cloud_region = Region(
            name=region['name'],
            co2_traces_filename=co2_traces_filename,
            datetime_co2intensity=co2_dataframe,
            neighbors=region['neighbors'],
            latency_sec=region['latency_sec'],
            bandwidth_mbps=region['bandwidth_mbps']
        )
        regions.append(cloud_region)

        # Check for zones, if present, to add edge regions
        for zone in region.get('zones', []):
            co2_traces_filename = zone['co2_traces_file']
            co2_dataframe = read_traces_file(zone['co2_traces_file'], col_datetime, col_co2intensity, start_date,
                                             end_date)

            edge_region = Region(
                name=zone['name'],
                co2_traces_filename=co2_traces_filename,
                datetime_co2intensity=co2_dataframe,
                neighbors=region['neighbors'],
                latency_sec=zone['latency_sec'],
                bandwidth_mbps=zone['bandwidth_mbps'],
                default_cloud=region['name']
            )

            regions.append(edge_region)

    return regions

def init_simulation(config):
    seed = config.getint(conf.SEC_SIM, conf.SEED, fallback=1)
    seed_sequence = SeedSequence(seed)

    regions = regions_setup(config)

    bandwidth_mbps = {}
    latencies = {}

    for region in regions:
        for target_name, latency in region.latency_sec.items():
            # Find the target Region object by name
            target_region = next((r for r in regions if r.name == target_name), None)
            if target_region:
                # Create the pair as a sorted tuple of Region objects
                key_pair = tuple(sorted((region, target_region), key=lambda r: r.name))
                if key_pair not in latencies:
                    latencies[key_pair] = latency

        for target_name, bandwidth in region.bandwidth_mbps.items():
            # Find the target Region object by name
            target_region = next((r for r in regions if r.name == target_name), None)
            if target_region:
                # Create the pair as a sorted tuple of Region objects
                key_pair = tuple(sorted((region, target_region), key=lambda r: r.name))
                if key_pair not in bandwidth_mbps:
                    bandwidth_mbps[key_pair] = bandwidth

    #print("===latencies: ",latencies)
    #print("===bandwidth_mbps: ", bandwidth_mbps)

    # Infrastructure
    infra = Infrastructure(regions, latencies, bandwidth_mbps)

    # Read spec file
    spec_file_name = config.get(conf.SEC_SIM, conf.SPEC_FILE, fallback=None)
    classes, functions, node2arrivals, function_variants, variants = read_spec_file(spec_file_name, infra, config)

    sim = Simulation(config, seed_sequence, infra, functions, classes, node2arrivals, function_variants, variants)
    return sim


def main():
    DEFAULT_CONFIG_FILE = "config.ini"
    config_file = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG_FILE
    config = conf.parse_config_file(config_file)
    simulation = init_simulation(config)
    final_stats = simulation.run()
    print("co2_emission_totalOld: ",final_stats.co2_emission_totalOld)
    print("co2_emission_total: ",final_stats.co2_emission_total)

    '''
    instant_u = simulation.instant_utilization_tmp_dict
    lp_u = simulation.lp_utilization_tmp_dict
    print("instant u: ",instant_u)
    print("lp u: ",lp_u)

    print("lp u AVG per node:")
    for node, dq in lp_u.items():
        print(f"  {node}: {avg_deque(dq):.6f}  (n={len(dq)})")

    print("instant u AVG per node:")
    for node, dq in instant_u.items():
        print(f"  {node}: {avg_deque(dq):.6f}  (n={len(dq)})")

    instant_e = simulation.instant_energy_tmp_dict
    lp_e = simulation.lp_energy_tmp_dict
    print("instant e: ",instant_e)
    print("lp e: ",lp_e)

    print("lp e AVG per node:")
    for node, dq in lp_e.items():
        print(f"  {node}: {avg_deque(dq):.6f}  (n={len(dq)})")

    print("instant e AVG per node:")
    for node, dq in instant_e.items():
        print(f"  {node}: {avg_deque(dq):.6f}  (n={len(dq)})")
    '''


def avg_deque(dq):
    return (sum(dq) / len(dq)) if dq else 0.0
if __name__ == "__main__":
    main()
