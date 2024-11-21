import sys
import os
import argparse
import pandas as pd
from numpy.random import SeedSequence, default_rng
import numpy as np
from scipy.stats import zipfian
import yaml
import tempfile

import faas
import conf
from arrivals import PoissonArrivalProcess, TraceArrivalProcess
from simulation import Simulation
from infrastructure import *
from main import read_spec_file

DEFAULT_CONFIG_FILE = "config.ini"
DEFAULT_OUT_DIR = "results"
DEFAULT_DURATION = 3600
SEEDS=[1,293,287844,2902,944,9573,102903,193,456,71]
PERCENTILES=np.array([1,5,10,25,50,75,90,95,99])/100.0


# Returns an open NamedTemporaryFile
# arrivals "single", "edge", "all"
def generate_temp_spec (seed_sequence, load_coeff=1.0, arrivals_mode="single", max_data_access_time=99, zipf_key_popularity=True, edge_memory=4096, external_data_store=False, n_keys=5, n_functions=5, cloud_nodes=5):
    outf = tempfile.NamedTemporaryFile(mode="w")

    n_edges = 5
    n_cloud = cloud_nodes
    nodes = []

    for i in range(n_edges):
        n = {}
        n["name"] = f"edge_{i+1}"
        n["region"] = "edge"
        n["memory"] = edge_memory
        nodes.append(n)
    for i in range(n_cloud):
        n = {}
        n["name"] = f"cloud_{i+1}"
        n["region"] = "cloud"
        n["memory"] = 64000
        n["cloud_cost"] = 0.0
        nodes.append(n)

    classes = [{'name': 'standard', 'max_resp_time': 99.0, 'utility': 0.01, 'arrival_weight': 1.0}]

    functions = [{'name': 'f1', 'memory': 512, 'duration_mean': 0.4, 'duration_scv': 1.0, 'init_mean': 0.5}, {'name': 'f2', 'memory': 512, 'duration_mean': 0.2, 'duration_scv': 1.0, 'init_mean': 0.25}, {'name': 'f3', 'memory': 128, 'duration_mean': 0.3, 'duration_scv': 1.0, 'init_mean': 0.6}, {'name': 'f4', 'memory': 1024, 'duration_mean': 0.25, 'duration_scv': 1.0, 'init_mean': 0.25}, {'name': 'f5', 'memory': 256, 'duration_mean': 0.45, 'duration_scv': 1.0, 'init_mean': 0.5}]
    while len(functions) < n_functions:
        f = functions[0].copy()
        f["name"] = f"f{len(functions)}"
        functions.append(f)

    key_rng = default_rng(seed_sequence.spawn(1)[0])
    KEYS_PER_FUNCTION = n_keys
    print(KEYS_PER_FUNCTION)
    for f in functions:
        f["max_data_access_time"] = max_data_access_time
        # Accessed keys in (k1, k2, ..., k100)
        f["keys"] = []
        if not zipf_key_popularity:
            keys = key_rng.integers(0, 100, size=KEYS_PER_FUNCTION)
        else:
            keys = zipfian.rvs(1, 101, size=KEYS_PER_FUNCTION, random_state=key_rng)-1
        for k in keys:
            prob = key_rng.choice([0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 1.0], size=1)
            f["keys"].append({"key": f"k{k}", "probability": float(prob)})
   

    total_fun_weight = sum([f["duration_mean"]*f["memory"] for f in functions])

    arrivals = []
    if arrivals_mode == "single":
        total_load = 8000*load_coeff
        for f in functions:
            rate = total_load/len(functions)/(f["duration_mean"]*f["memory"])
            arrivals.append({"node": "edge_1",
                            "function": f["name"],
                            "rate": rate,
                            "dynamic_coeff": 1.0
                            })
    elif arrivals_mode == "edge":
        edge_nodes = [n for n in nodes if "edge" in n["name"]]
        total_load = 16000*load_coeff
        load_per_node = total_load/len(edge_nodes)
        for n in edge_nodes:
            for f in functions:
                rate = load_per_node/len(functions)/(f["duration_mean"]*f["memory"])
                arrivals.append({"node": n["name"],
                                "function": f["name"],
                                "rate": rate,
                                 "dynamic_coeff": 1.0})
    elif arrivals_mode == "edge-alt":
        edge_nodes = [n for n in nodes if "edge" in n["name"]]
        total_load = 16000*load_coeff
        load_per_func = total_load/len(functions)
        i_edge=0
        for f in functions:
            n = edge_nodes[i_edge]
            i_edge = (i_edge+1)%len(edge_nodes)
            rate = load_per_func/(f["duration_mean"]*f["memory"])
            arrivals.append({"node": n["name"],
                            "function": f["name"],
                            "rate": rate,
                                "dynamic_coeff": 1.0})
    elif arrivals_mode == "all":
        total_load = 32000*load_coeff
        load_per_node = total_load/len(nodes)
        for n in nodes:
            for f in functions:
                rate = load_per_node/len(functions)/(f["duration_mean"]*f["memory"])
                arrivals.append({"node": n["name"],
                                "function": f["name"],
                                "rate": rate,
                                 "dynamic_coeff": 1.0})

    if external_data_store:
        n = {}
        n["name"] = f"datastore"
        n["region"] = "cloud"
        n["memory"] = 0
        n["speedup"] = 0
        nodes.append(n)

    spec = {'classes': classes, 'nodes': nodes, 'functions': functions, 'arrivals': arrivals}
    outf.write(yaml.dump(spec))
    outf.flush()
    print(yaml.dump(spec))
    return outf


def print_results (results, filename=None):
    for line in results:
        print(line)
    if filename is not None:
        with open(filename, "w") as of:
            for line in results:
                print(line,file=of)

def default_infra():
    # Regions
    reg_cloud = Region("cloud", reg1_timestamp_co2intensity_reg)
    reg_edge = Region("edge", reg1_timestamp_co2intensity_reg, reg_cloud)
    regions = [reg_edge, reg_cloud]
    # Latency
    latencies = {}
    bandwidth_mbps = {(reg_edge,reg_edge): 100.0, (reg_cloud,reg_cloud): 1000.0,\
            (reg_edge,reg_cloud): 100.0}
    # Infrastructure
    return Infrastructure(regions, latencies, bandwidth_mbps)

def generate_latencies (infra, rng):
    enodes = infra.get_edge_nodes()
    cnodes = infra.get_cloud_nodes()
    for e1 in enodes:
        for e2 in enodes:
            if e1 == e2:
                continue
            infra.latency[(e1,e2)] = float(rng.uniform(1,20))/1000
    for c1 in cnodes:
        for c2 in cnodes:
            if c1 == c2:
                continue
            infra.latency[(c1,c2)] = float(rng.uniform(1,10))/1000
    for e in enodes:
        for c in cnodes:
            infra.latency[(e,c)] = float(rng.uniform(10,100))/1000

    nodes = infra.get_nodes(ignore_non_processing=False)
    datastore = None
    for n in nodes:
        if n.name == "datastore":
            datastore = n
            break
    if datastore is not None:
        for e in enodes:
            infra.latency[(e,datastore)] = float(rng.uniform(10,100))/1000
        for c in cnodes:
            infra.latency[(c,datastore)] = float(rng.uniform(1,15))/1000


def _experiment (config, seed_sequence, infra, spec_file_name):
    classes, functions, node2arrivals  = read_spec_file (spec_file_name, infra, config)
    generate_latencies(infra, default_rng(seed_sequence.spawn(1)[0]))

    with tempfile.NamedTemporaryFile() as rtf:
        config.set(conf.SEC_SIM, conf.RESP_TIMES_FILE, rtf.name)
        sim = Simulation(config, seed_sequence, infra, functions, classes, node2arrivals)
        final_stats = sim.run()
        del(sim)

        # Retrieve response times
        df = pd.read_csv(rtf.name)
        # Compute percentiles
        rt_p = {f"RT-{k}": v for k,v in df.RT.quantile(PERCENTILES).items()}
        dat_p = {f"DAT-{k}": v for k,v in df.DataAccess.quantile(PERCENTILES).items()}

    return final_stats, df, rt_p, dat_p

def relevant_stats_dict (stats):
    result = {}
    result["Utility"] = stats.utility
    result["Penalty"] = stats.penalty
    result["NetUtility"] = stats.utility-stats.penalty
    result["Cost"] = stats.cost
    result["DataMigrations"] = stats.data_migrations_count
    result["DataTardiness"] = stats.data_access_tardiness
    result["DataMigratedBytes"] = stats.data_migrated_bytes
    result["MigPolicyExecTime"] = stats._mig_policy_update_time_sum/stats._mig_policy_updates if stats._mig_policy_updates > 0 else 0
    for f in stats.data_access_violations:
        result[f"DataAccessViolations-{f}"] = stats.data_access_violations[f]
    for f in stats.data_access_violations:
        completions = 0
        for _f,_c,_n in stats.completions:
            if _f == f:
                completions += stats.completions[(f,_c,_n)]
        result[f"Completions-{f}"] = completions
    result["DataAccessViolations"] = sum(stats.data_access_violations.values())
    result["Completions"] = sum(stats.completions.values())

    # TODO: Assuming single class here!
    compls={}
    for f,c,n in stats.completions:
        val = stats.completions[(f,c,n)]
        result[f"Compl-{n}-{f}"] = val
        compls[n] = compls.get(n,0) + val
    for n,val in compls.items():
        result[f"Compl-{n}"] = val

    for n in stats._memory_usage_t0:
        result[f"avgMemUtil-{n}"] = stats._memory_usage_area[n]/stats.sim.t/n.total_memory


    return result

def experiment_datastore (args, config):
    results = []
    exp_tag = "datastoreTard"
    outfile=os.path.join(DEFAULT_OUT_DIR,f"{exp_tag}.csv")


    config.set(conf.SEC_POLICY, conf.CLOUD_COLD_START_EST_STRATEGY, "naive")
    config.set(conf.SEC_POLICY, conf.EDGE_COLD_START_EST_STRATEGY, "naive")
    config.set(conf.SEC_POLICY, conf.LOCAL_COLD_START_EST_STRATEGY, "naive")
    config.set(conf.SEC_POLICY, conf.POLICY_UPDATE_INTERVAL, "120")
    config.set(conf.SEC_POLICY, conf.POLICY_ARRIVAL_RATE_ALPHA, "0.3")
    config.set(conf.SEC_POLICY, conf.HOURLY_BUDGET, "999")


    OFFLOADING_POLICIES = ["basic", "random-stateful", "state-aware", "state-aware-always-offload"]
    MIGRATION_POLICIES = ["none", "random", "greedy", "ilp"]

    # Check existing results
    old_results = None
    if not args.force:
        try:
            old_results = pd.read_csv(outfile)
        except:
            pass

    for zipf_popularity in [True,False]:
        for edge_memory in [4096]:
            for workload_scenario in ["edge-alt", "edge"]:
                for seed in SEEDS:
                    config.set(conf.SEC_SIM, conf.SEED, str(seed))
                    seed_sequence = SeedSequence(seed)

                    for max_dat in [0.100, 0.200]:
                        for mig_pol in MIGRATION_POLICIES:
                            config.set(conf.SEC_STATEFUL, conf.POLICY_NAME, mig_pol)
                            for pol in OFFLOADING_POLICIES:
                                config.set(conf.SEC_POLICY, conf.POLICY_NAME, pol)

                                for load_coeff in [1.0]:

                                    keys = {}
                                    keys["Load"] = load_coeff
                                    keys["EdgeMem"] = edge_memory
                                    keys["ZipfPopularity"] = zipf_popularity
                                    keys["WorkloadScenario"] = workload_scenario
                                    keys["MaxDataAccessTime"] = max_dat
                                    keys["OffloadingPolicy"] = pol
                                    keys["MigrationPolicy"] = mig_pol
                                    keys["Seed"] = seed

                                    run_string = "_".join([f"{k}{v}" for k,v in keys.items()])

                                    # Check if we can skip this run
                                    if old_results is not None and not\
                                            old_results[(old_results.Seed == seed) &\
                                                (old_results.OffloadingPolicy == pol) &\
                                                (old_results.Load == load_coeff) &\
                                                (old_results.EdgeMem == edge_memory) &\
                                                (old_results.WorkloadScenario == workload_scenario) &\
                                                (old_results.ZipfPopularity == zipf_popularity) &\
                                                (old_results.MaxDataAccessTime == max_dat) &\
                                                (old_results.MigrationPolicy == mig_pol)].empty:
                                        print("Skipping conf") 
                                        continue 
                                    temp_spec_file = generate_temp_spec (seed_sequence, max_data_access_time=max_dat, load_coeff=load_coeff, zipf_key_popularity=zipf_popularity, arrivals_mode=workload_scenario, edge_memory=edge_memory, external_data_store=True)
                                    infra = default_infra()
                                    stats, resptimes, resptimes_perc, dat_perc = _experiment(config, seed_sequence, infra, temp_spec_file.name)
                                    temp_spec_file.close()
                                    with open(os.path.join(DEFAULT_OUT_DIR, f"{exp_tag}_{run_string}.json"), "w") as of:
                                        stats.print(of)
                                    #resptimes.to_csv(os.path.join(DEFAULT_OUT_DIR, f"{exp_tag}_{run_string}_rt.csv"), index=False)

                                    result=dict(list(keys.items()) + list(relevant_stats_dict(stats).items()) +\
                                            list(resptimes_perc.items()) + list(dat_perc.items()))
                                    results.append(result)
                                    print(result)

                                    resultsDf = pd.DataFrame(results)
                                    if old_results is not None:
                                        resultsDf = pd.concat([old_results, resultsDf])
                                    resultsDf.to_csv(outfile, index=False)
    
    resultsDf = pd.DataFrame(results)
    if old_results is not None:
        resultsDf = pd.concat([old_results, resultsDf])
    resultsDf.to_csv(outfile, index=False)
    print(resultsDf.groupby("OffloadingPolicy").mean())

    with open(os.path.join(DEFAULT_OUT_DIR, f"{exp_tag}_conf.ini"), "w") as of:
        config.write(of)

def experiment_scalability (args, config):
    results = []
    exp_tag = "scalability"
    outfile=os.path.join(DEFAULT_OUT_DIR,f"{exp_tag}.csv")


    config.set(conf.SEC_SIM, conf.CLOSE_DOOR_TIME, str(600))
    config.set(conf.SEC_POLICY, conf.CLOUD_COLD_START_EST_STRATEGY, "naive")
    config.set(conf.SEC_POLICY, conf.EDGE_COLD_START_EST_STRATEGY, "naive")
    config.set(conf.SEC_POLICY, conf.LOCAL_COLD_START_EST_STRATEGY, "naive")
    config.set(conf.SEC_POLICY, conf.POLICY_UPDATE_INTERVAL, "120")
    config.set(conf.SEC_POLICY, conf.POLICY_ARRIVAL_RATE_ALPHA, "0.3")
    config.set(conf.SEC_POLICY, conf.HOURLY_BUDGET, "999")


    OFFLOADING_POLICIES = ["state-aware"]
    MIGRATION_POLICIES = ["ilp"]

    # Check existing results
    old_results = None
    if not args.force:
        try:
            old_results = pd.read_csv(outfile)
        except:
            pass

    # TODO: different workloads settings

    for cloud_nodes in [5,10,20,30]:
        for n_keys in [5]:
            for n_functions in [5,10,15,20,25,30]:
                for seed in SEEDS[:5]:
                    config.set(conf.SEC_SIM, conf.SEED, str(seed))
                    seed_sequence = SeedSequence(seed)

                    for max_dat in [0.2]:
                        for mig_pol in MIGRATION_POLICIES:
                            config.set(conf.SEC_STATEFUL, conf.POLICY_NAME, mig_pol)
                            for pol in OFFLOADING_POLICIES:
                                config.set(conf.SEC_POLICY, conf.POLICY_NAME, pol)

                                for load_coeff in [1.0]:

                                    keys = {}
                                    keys["Load"] = load_coeff
                                    keys["Keys"] = n_keys
                                    keys["CloudNodes"] = cloud_nodes
                                    keys["Functions"] = n_functions
                                    keys["MaxDataAccessTime"] = max_dat
                                    keys["OffloadingPolicy"] = pol
                                    keys["MigrationPolicy"] = mig_pol
                                    keys["Seed"] = seed

                                    run_string = "_".join([f"{k}{v}" for k,v in keys.items()])

                                    # Check if we can skip this run
                                    if old_results is not None and not\
                                            old_results[(old_results.Seed == seed) &\
                                                (old_results.OffloadingPolicy == pol) &\
                                                (old_results.Load == load_coeff) &\
                                                (old_results.Keys == n_keys) &\
                                                (old_results.Functions == n_functions) &\
                                                (old_results.CloudNodes == cloud_nodes) &\
                                                (old_results.MaxDataAccessTime == max_dat) &\
                                                (old_results.MigrationPolicy == mig_pol)].empty:
                                        print("Skipping conf") 
                                        continue 
                                    temp_spec_file = generate_temp_spec (seed_sequence, max_data_access_time=max_dat, load_coeff=load_coeff, zipf_key_popularity=True, cloud_nodes=cloud_nodes, arrivals_mode="edge", edge_memory=4096, n_keys=n_keys, n_functions=n_functions)
                                    infra = default_infra()
                                    stats, resptimes, resptimes_perc, dat_perc = _experiment(config, seed_sequence, infra, temp_spec_file.name)
                                    temp_spec_file.close()
                                    with open(os.path.join(DEFAULT_OUT_DIR, f"{exp_tag}_{run_string}.json"), "w") as of:
                                        stats.print(of)
                                    #resptimes.to_csv(os.path.join(DEFAULT_OUT_DIR, f"{exp_tag}_{run_string}_rt.csv"), index=False)

                                    result=dict(list(keys.items()) + list(relevant_stats_dict(stats).items()) +\
                                            list(resptimes_perc.items()) + list(dat_perc.items()))
                                    results.append(result)
                                    print(result)

                                    resultsDf = pd.DataFrame(results)
                                    if old_results is not None:
                                        resultsDf = pd.concat([old_results, resultsDf])
                                    resultsDf.to_csv(outfile, index=False)
    
    resultsDf = pd.DataFrame(results)
    if old_results is not None:
        resultsDf = pd.concat([old_results, resultsDf])
    resultsDf.to_csv(outfile, index=False)
    print(resultsDf.groupby("OffloadingPolicy").mean())

    with open(os.path.join(DEFAULT_OUT_DIR, f"{exp_tag}_conf.ini"), "w") as of:
        config.write(of)

def experiment_main (args, config):
    results = []
    exp_tag = "main"
    outfile=os.path.join(DEFAULT_OUT_DIR,f"{exp_tag}.csv")


    config.set(conf.SEC_POLICY, conf.CLOUD_COLD_START_EST_STRATEGY, "naive")
    config.set(conf.SEC_POLICY, conf.EDGE_COLD_START_EST_STRATEGY, "naive")
    config.set(conf.SEC_POLICY, conf.LOCAL_COLD_START_EST_STRATEGY, "naive")
    config.set(conf.SEC_POLICY, conf.POLICY_UPDATE_INTERVAL, "120")
    config.set(conf.SEC_POLICY, conf.POLICY_ARRIVAL_RATE_ALPHA, "0.3")
    config.set(conf.SEC_POLICY, conf.HOURLY_BUDGET, "999")


    OFFLOADING_POLICIES = ["basic", "random-stateful", "state-aware", "state-aware-always-offload"]
    MIGRATION_POLICIES = ["none", "random", "greedy", "ilp"]

    # Check existing results
    old_results = None
    if not args.force:
        try:
            old_results = pd.read_csv(outfile)
        except:
            pass

    # TODO: different workloads settings

    for zipf_popularity in [True,False]:
        for edge_memory in [4096]:
            for workload_scenario in ["edge-alt", "edge"]:
                for seed in SEEDS:
                    config.set(conf.SEC_SIM, conf.SEED, str(seed))
                    seed_sequence = SeedSequence(seed)

                    for max_dat in [0.100, 0.200, 1]:
                        for mig_pol in MIGRATION_POLICIES:
                            config.set(conf.SEC_STATEFUL, conf.POLICY_NAME, mig_pol)
                            for pol in OFFLOADING_POLICIES:
                                config.set(conf.SEC_POLICY, conf.POLICY_NAME, pol)

                                for load_coeff in [1.0]:

                                    keys = {}
                                    keys["Load"] = load_coeff
                                    keys["EdgeMem"] = edge_memory
                                    keys["ZipfPopularity"] = zipf_popularity
                                    keys["WorkloadScenario"] = workload_scenario
                                    keys["MaxDataAccessTime"] = max_dat
                                    keys["OffloadingPolicy"] = pol
                                    keys["MigrationPolicy"] = mig_pol
                                    keys["Seed"] = seed

                                    run_string = "_".join([f"{k}{v}" for k,v in keys.items()])

                                    # Check if we can skip this run
                                    if old_results is not None and not\
                                            old_results[(old_results.Seed == seed) &\
                                                (old_results.OffloadingPolicy == pol) &\
                                                (old_results.Load == load_coeff) &\
                                                (old_results.EdgeMem == edge_memory) &\
                                                (old_results.WorkloadScenario == workload_scenario) &\
                                                (old_results.ZipfPopularity == zipf_popularity) &\
                                                (old_results.MaxDataAccessTime == max_dat) &\
                                                (old_results.MigrationPolicy == mig_pol)].empty:
                                        print("Skipping conf") 
                                        continue 
                                    temp_spec_file = generate_temp_spec (seed_sequence, max_data_access_time=max_dat, load_coeff=load_coeff, zipf_key_popularity=zipf_popularity, arrivals_mode=workload_scenario, edge_memory=edge_memory)
                                    infra = default_infra()
                                    stats, resptimes, resptimes_perc, dat_perc = _experiment(config, seed_sequence, infra, temp_spec_file.name)
                                    temp_spec_file.close()
                                    with open(os.path.join(DEFAULT_OUT_DIR, f"{exp_tag}_{run_string}.json"), "w") as of:
                                        stats.print(of)
                                    #resptimes.to_csv(os.path.join(DEFAULT_OUT_DIR, f"{exp_tag}_{run_string}_rt.csv"), index=False)

                                    result=dict(list(keys.items()) + list(relevant_stats_dict(stats).items()) +\
                                            list(resptimes_perc.items()) + list(dat_perc.items()))
                                    results.append(result)
                                    print(result)

                                    resultsDf = pd.DataFrame(results)
                                    if old_results is not None:
                                        resultsDf = pd.concat([old_results, resultsDf])
                                    resultsDf.to_csv(outfile, index=False)
    
    resultsDf = pd.DataFrame(results)
    if old_results is not None:
        resultsDf = pd.concat([old_results, resultsDf])
    resultsDf.to_csv(outfile, index=False)
    print(resultsDf.groupby("OffloadingPolicy").mean())

    with open(os.path.join(DEFAULT_OUT_DIR, f"{exp_tag}_conf.ini"), "w") as of:
        config.write(of)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment', action='store', required=False, default="", type=str)
    parser.add_argument('--force', action='store_true', required=False, default=False)
    parser.add_argument('--debug', action='store_true', required=False, default=False)
    parser.add_argument('--seed', action='store', required=False, default=None, type=int)

    args = parser.parse_args()

    config = conf.parse_config_file("default.ini")
    config.set(conf.SEC_SIM, conf.STAT_PRINT_INTERVAL, "-1")
    config.set(conf.SEC_SIM, conf.CLOSE_DOOR_TIME, str(DEFAULT_DURATION))

    if args.debug:
        args.force = True
        SEEDS=SEEDS[:1]

    if args.seed is not None:
        SEEDS = [int(args.seed)]
    
    if args.experiment.lower() == "a":
        experiment_main(args, config)
    if args.experiment.lower() == "d":
        experiment_datastore(args, config)
    if args.experiment.lower() == "s":
        experiment_scalability(args, config)
    else:
        print("Unknown experiment!")
        exit(1)
