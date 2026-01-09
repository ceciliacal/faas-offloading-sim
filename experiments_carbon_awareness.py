import tempfile
import os
import argparse
import pandas as pd
import numpy as np
import yaml

from spec import generate_regions_yaml, generate_random_temp_spec_variants
from simulation import Simulation
from infrastructure import *
from main import read_spec_file
from numpy.random import SeedSequence, default_rng

DEFAULT_CONFIG_FILE = "config.ini"
DEFAULT_OUT_DIR = "090126"
DEFAULT_DURATION = 259200
#SEEDS=[1,293,287844,2902,944,9573,102903,193,456,71]
PERCENTILES=np.array([1,5,10,25,50,75,90,95,99])/100.0
COST_REG_CLOUD_HIGH = 0.00003
COST_REG_CLOUD_LOW = 0.00001
BUDGETS=[0.5, 5, 20, 50]



def print_results (results, filename=None):
    for line in results:
        print(line)
    if filename is not None:
        with open(filename, "w") as of:
            for line in results:
                print(line,file=of)

def read_traces_file(filename, col_datetime, col_co2intensity, start_date, end_date):
    total_df = pd.read_csv(filename)
    start_date = pd.to_datetime(start_date).date()
    end_date = pd.to_datetime(end_date).date()

    total_df[col_datetime] = pd.to_datetime(total_df[col_datetime])
    weekly_df = total_df[(total_df[col_datetime].dt.date >= start_date) & (total_df[col_datetime].dt.date <= end_date)]
    df = weekly_df[[col_datetime, col_co2intensity]]
    return df

def regions_setup(config, is_edge_green=True):

    col_datetime = conf.CO2_TRACES_COL_TIMESTAMP
    col_co2intensity = conf.CO2_TRACES_COL_INTENSITY_DIRECT
    start_date = config.get(conf.SEC_CARBON, conf.START_DATE, fallback=None)
    end_date = config.get(conf.SEC_CARBON, conf.END_DATE, fallback=None)

    regions_file_path = generate_regions_yaml(is_edge_green)
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

def default_infra(is_edge_green):
    # Regions
    regions = regions_setup(config,is_edge_green)

    # Latency
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
    # Infrastructure
    return Infrastructure(regions, latencies, bandwidth_mbps)


def _experiment (config, seed_sequence, infra, spec_file_name, return_resp_times_stats=False):
    classes, functions, node2arrivals, function_variants, variants  = read_spec_file (spec_file_name, infra, config)
    #generate_latencies(infra, default_rng(seed_sequence.spawn(1)[0]))

    with tempfile.NamedTemporaryFile() as rtf:
        if return_resp_times_stats:
            config.set(conf.SEC_SIM, conf.RESP_TIMES_FILE, rtf.name)
        sim = Simulation(config, seed_sequence, infra, functions, classes, node2arrivals, function_variants, variants)
        final_stats = sim.run()
        del(sim)

        if return_resp_times_stats:
            # Retrieve response times
            df = pd.read_csv(rtf.name)
            # Compute percentiles
            rt_p = {f"RT-{k}": v for k,v in df.RT.quantile(PERCENTILES).items()}
            dat_p = {f"DAT-{k}": v for k,v in df.DataAccess.quantile(PERCENTILES).items()}

    if return_resp_times_stats:
        return final_stats, df, rt_p, dat_p
    else:
        return final_stats

def relevant_stats_dict (stats):
    result = {}
    result["Utility"] = stats.utility
    result["Penalty"] = stats.penalty
    result["NetUtility"] = stats.utility-stats.penalty
    result["Cost"] = stats.cost
    result["BudgetExcessPerc"] = max(0, (stats.cost-stats.budget)/stats.budget*100)

    result["TotalProcTime"] = stats.total_processing_time
    result["CO2EmissTotal"] = stats.co2_emission_total
    result["CO2EmissTotalOld"] = stats.co2_emission_totalOld
    result["ExtArrivals"] = sum(stats.ext_arrivals.values())

    return result

def experiment_main_comparison_brown_greedy(args, config, seeds, flag_seeds):
    results = []
    exp_tag = "mainComparisonBrown_Greedy"+ "_" + flag_seeds
    config.set(conf.SEC_POLICY, conf.SPLIT_BUDGET_AMONG_EDGE_NODES, "false")
    results_directory = DEFAULT_OUT_DIR + "_results_greedy"
    os.makedirs(results_directory, exist_ok=True)
    outfile = os.path.join(results_directory, f"{exp_tag}.csv")

    config.set(conf.SEC_POLICY, conf.POLICY_UPDATE_INTERVAL, "600")
    config.set(conf.SEC_POLICY, conf.POLICY_ARRIVAL_RATE_ALPHA, "0.3")

    POLICIES = ["greedy-multi-region",
                "greedy-carbon-aware",
                "greedy-carbon-aware-strict"]

    # Check existing results
    old_results = None
    if not args.force:
        try:
            old_results = pd.read_csv(outfile)
        except:
            pass

    variants_mode = [0,1] #variants mode: 0 inactive, 1 active with speedup=utility for each variants

    for seed in seeds:
        config.set(conf.SEC_SIM, conf.SEED, str(seed))
        for budget in BUDGETS:
            config.set(conf.SEC_POLICY, conf.HOURLY_BUDGET, str(budget))
            for variant_mode in variants_mode:
                for pol in POLICIES:
                    config.set(conf.SEC_POLICY, conf.POLICY_NAME, pol)

                    keys = {
                        "Policy": pol,
                        "Budget": budget,
                        "Seed": seed,
                        "Variant_mode": variant_mode
                    }

                    run_string = "_".join([f"{k}{v}" for k, v in keys.items()])

                    # Check if we can skip this run
                    if old_results is not None and not old_results[
                       (old_results.Policy == pol) &
                       (old_results.Budget == budget) &
                        (old_results.Seed == seed) &
                        (old_results.Variant_mode == variant_mode)
                    ].empty:
                        print("Skipping conf")
                        continue

                    seed_sequence = SeedSequence(seed)
                    rng = default_rng(seed_sequence.spawn(1)[0])
                    temp_spec_file = generate_random_temp_spec_variants(
                        rng, variants_mode=variant_mode, arrivals_to_single_node=False,
                        cloud_cost_reg_a=COST_REG_CLOUD_LOW, cloud_cost_reg_b=COST_REG_CLOUD_HIGH

                    )
                    infra = default_infra(is_edge_green=False)
                    stats = _experiment(config, seed_sequence, infra, temp_spec_file.name)
                    temp_spec_file.close()

                    with open(os.path.join(results_directory, f"{exp_tag}_{run_string}.json"), "w") as of:
                        stats.print(of)

                    result = dict(list(keys.items()) + list(relevant_stats_dict(stats).items()))
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

    with open(os.path.join(results_directory, f"{exp_tag}_conf.ini"), "w") as of:
        config.write(of)


def experiment_main_comparison_brown_baseline(args, config, seeds, flag_seeds):
    results = []
    exp_tag = "mainComparisonBrown_Baseline" + "_" + flag_seeds
    config.set(conf.SEC_POLICY, conf.SPLIT_BUDGET_AMONG_EDGE_NODES, "false")
    results_directory = DEFAULT_OUT_DIR + "_results_baseline"
    os.makedirs(results_directory, exist_ok=True)
    outfile = os.path.join(results_directory, f"{exp_tag}.csv")

    config.set(conf.SEC_POLICY, conf.POLICY_UPDATE_INTERVAL, "600")
    config.set(conf.SEC_POLICY, conf.POLICY_ARRIVAL_RATE_ALPHA, "0.3")

    POLICIES = ["random-multi-region","random-multi-region-no-drop",
                "basic-multi-region"]

    # Check existing results
    old_results = None
    if not args.force:
        try:
            old_results = pd.read_csv(outfile)
        except:
            pass

    variants_mode = [0,1] #variants mode: 0 inactive, 1 active with speedup=utility for each variants

    for seed in seeds:
        config.set(conf.SEC_SIM, conf.SEED, str(seed))
        for budget in BUDGETS:
            config.set(conf.SEC_POLICY, conf.HOURLY_BUDGET, str(budget))
            for variant_mode in variants_mode:
                for pol in POLICIES:
                    config.set(conf.SEC_POLICY, conf.POLICY_NAME, pol)

                    keys = {
                        "Policy": pol,
                        "Budget": budget,
                        "Seed": seed,
                        "Variant_mode": variant_mode
                    }

                    run_string = "_".join([f"{k}{v}" for k, v in keys.items()])

                    # Check if we can skip this run
                    if old_results is not None and not old_results[
                       (old_results.Policy == pol) &
                       (old_results.Budget == budget) &
                        (old_results.Seed == seed) &
                        (old_results.Variant_mode == variant_mode)
                    ].empty:
                        print("Skipping conf")
                        continue

                    seed_sequence = SeedSequence(seed)
                    rng = default_rng(seed_sequence.spawn(1)[0])
                    temp_spec_file = generate_random_temp_spec_variants(
                        rng, variants_mode=variant_mode, arrivals_to_single_node=False,
                        cloud_cost_reg_a=COST_REG_CLOUD_LOW, cloud_cost_reg_b=COST_REG_CLOUD_HIGH

                    )
                    infra = default_infra(is_edge_green=False)
                    stats = _experiment(config, seed_sequence, infra, temp_spec_file.name)
                    temp_spec_file.close()

                    with open(os.path.join(results_directory, f"{exp_tag}_{run_string}.json"), "w") as of:
                        stats.print(of)

                    result = dict(list(keys.items()) + list(relevant_stats_dict(stats).items()))
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

    with open(os.path.join(results_directory, f"{exp_tag}_conf.ini"), "w") as of:
        config.write(of)

def experiment_main_comparison_brown(args, config, seeds, flag_seeds):
    results = []
    exp_tag = "mainComparisonBrown" + "_" + flag_seeds
    config.set(conf.SEC_POLICY, conf.SPLIT_BUDGET_AMONG_EDGE_NODES, "false")
    results_directory = DEFAULT_OUT_DIR + "_results_probabilistic"
    os.makedirs(results_directory, exist_ok=True)
    outfile = os.path.join(results_directory, f"{exp_tag}.csv")

    config.set(conf.SEC_POLICY, conf.POLICY_UPDATE_INTERVAL, "600")
    config.set(conf.SEC_POLICY, conf.POLICY_ARRIVAL_RATE_ALPHA, "0.3")

    POLICIES = ["probabilistic-carbon-aware"]
    variants_mode = [0,1] #variants mode: 0 inactive, 1 active with speedup=utility for each variants

    # Check existing results
    old_results = None
    if not args.force:
        try:
            old_results = pd.read_csv(outfile)
        except:
            pass

    for seed in seeds:
        config.set(conf.SEC_SIM, conf.SEED, str(seed))
        for budget in BUDGETS:
            config.set(conf.SEC_POLICY, conf.HOURLY_BUDGET, str(budget))
            for variant_mode in variants_mode:
                for pol in POLICIES:

                    config.set(conf.SEC_POLICY, conf.POLICY_NAME, pol)

                    of_values = [
                        (0.0, 1.0),  # of-alpha=0, of-beta=1
                        (1.0, 0.0),  # of-alpha=1, of-beta=0
                    ]

                    for of_alpha, of_beta in of_values:
                        config.set(conf.SEC_POLICY, conf.ALPHA, str(of_alpha))
                        config.set(conf.SEC_POLICY, conf.BETA, str(of_beta))

                        keys = {
                            "Policy": pol,
                            "Budget": budget,
                            "Seed": seed,
                            "Variant_mode": variant_mode,
                            "OF-Alpha": of_alpha,
                            "OF-Beta": of_beta,
                        }

                        run_string = "_".join([f"{k}{v}" for k, v in keys.items()])

                        # Check if we can skip this run
                        if old_results is not None and not old_results[

                            (old_results.Policy == pol) &
                            (old_results.Budget == budget) &
                            (old_results.Seed == seed) &
                            (old_results.Variant_mode == variant_mode) &
                            (old_results["OF-Alpha"] == of_alpha) &
                            (old_results["OF-Beta"] == of_beta)
                        ].empty:
                            print("Skipping conf")
                            continue

                        seed_sequence = SeedSequence(seed)
                        rng = default_rng(seed_sequence.spawn(1)[0])
                        temp_spec_file = generate_random_temp_spec_variants(
                            rng, variants_mode=variant_mode, arrivals_to_single_node=False,
                            cloud_cost_reg_a=COST_REG_CLOUD_LOW, cloud_cost_reg_b=COST_REG_CLOUD_HIGH
                        )
                        infra = default_infra(is_edge_green=False)
                        stats = _experiment(config, seed_sequence, infra, temp_spec_file.name)
                        temp_spec_file.close()

                        with open(os.path.join(results_directory, f"{exp_tag}_{run_string}.json"), "w") as of:
                            stats.print(of)

                        result = dict(list(keys.items()) + list(relevant_stats_dict(stats).items()))
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

    with open(os.path.join(results_directory, f"{exp_tag}_conf.ini"), "w") as of:
        config.write(of)

def experiment_main_comparison_brown_normalized(args, config, seeds, flag_seeds):
    results = []
    exp_tag = "mainComparisonBrown_normalized" + "_" + flag_seeds
    config.set(conf.SEC_POLICY, conf.SPLIT_BUDGET_AMONG_EDGE_NODES, "false")
    results_directory = DEFAULT_OUT_DIR + "_results_probabilistic"
    os.makedirs(results_directory, exist_ok=True)
    outfile = os.path.join(results_directory, f"{exp_tag}.csv")

    config.set(conf.SEC_POLICY, conf.POLICY_UPDATE_INTERVAL, "600")
    config.set(conf.SEC_POLICY, conf.POLICY_ARRIVAL_RATE_ALPHA, "0.3")

    POLICIES = ["probabilistic-carbon-aware"]
    variants_mode = [0,1] #variants mode: 0 inactive, 1 active with speedup=utility for each variants

    # Check existing results
    old_results = None
    if not args.force:
        try:
            old_results = pd.read_csv(outfile)
        except:
            pass

    for seed in seeds:
        config.set(conf.SEC_SIM, conf.SEED, str(seed))
        for budget in BUDGETS:
            config.set(conf.SEC_POLICY, conf.HOURLY_BUDGET, str(budget))
            for variant_mode in variants_mode:
                for pol in POLICIES:

                    config.set(conf.SEC_POLICY, conf.POLICY_NAME, pol)

                    of_values = [
                        (0.5, 0.5)  # of-alpha=0, of-beta=1
                    ]

                    for of_alpha, of_beta in of_values:
                        config.set(conf.SEC_POLICY, conf.ALPHA, str(of_alpha))
                        config.set(conf.SEC_POLICY, conf.BETA, str(of_beta))

                        keys = {
                            "Policy": pol,
                            "Budget": budget,
                            "Seed": seed,
                            "Variant_mode": variant_mode,
                            "OF-Alpha": of_alpha,
                            "OF-Beta": of_beta,
                        }

                        run_string = "_".join([f"{k}{v}" for k, v in keys.items()])

                        # Check if we can skip this run
                        if old_results is not None and not old_results[

                            (old_results.Policy == pol) &
                            (old_results.Budget == budget) &
                            (old_results.Seed == seed) &
                            (old_results.Variant_mode == variant_mode) &
                            (old_results["OF-Alpha"] == of_alpha) &
                            (old_results["OF-Beta"] == of_beta)
                        ].empty:
                            print("Skipping conf")
                            continue

                        seed_sequence = SeedSequence(seed)
                        rng = default_rng(seed_sequence.spawn(1)[0])
                        temp_spec_file = generate_random_temp_spec_variants(
                            rng, variants_mode=variant_mode, arrivals_to_single_node=False,
                            cloud_cost_reg_a=COST_REG_CLOUD_LOW, cloud_cost_reg_b=COST_REG_CLOUD_HIGH
                        )
                        infra = default_infra(is_edge_green=False)
                        stats = _experiment(config, seed_sequence, infra, temp_spec_file.name)
                        temp_spec_file.close()

                        with open(os.path.join(results_directory, f"{exp_tag}_{run_string}.json"), "w") as of:
                            stats.print(of)

                        result = dict(list(keys.items()) + list(relevant_stats_dict(stats).items()))
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

    with open(os.path.join(results_directory, f"{exp_tag}_conf.ini"), "w") as of:
        config.write(of)

def experiment_main_comparison_green(args, config, seeds, flag_seeds):
    results = []
    exp_tag = "mainComparisonGreen"+ "_" + flag_seeds
    config.set(conf.SEC_POLICY, conf.SPLIT_BUDGET_AMONG_EDGE_NODES, "false")
    results_directory = DEFAULT_OUT_DIR + "_results_probabilistic"
    os.makedirs(results_directory, exist_ok=True)
    outfile = os.path.join(results_directory, f"{exp_tag}.csv")

    config.set(conf.SEC_POLICY, conf.POLICY_UPDATE_INTERVAL, "600")
    config.set(conf.SEC_POLICY, conf.POLICY_ARRIVAL_RATE_ALPHA, "0.3")

    POLICIES = ["probabilistic-carbon-aware"]

    # Check existing results
    old_results = None
    if not args.force:
        try:
            old_results = pd.read_csv(outfile)
        except:
            pass

    variants_mode = [0,1] #variants mode: 0 inactive, 1 active with speedup=utility for each variants

    for seed in seeds:
        config.set(conf.SEC_SIM, conf.SEED, str(seed))
        for budget in BUDGETS:
            config.set(conf.SEC_POLICY, conf.HOURLY_BUDGET, str(budget))
            for variant_mode in variants_mode:
                for pol in POLICIES:
                    config.set(conf.SEC_POLICY, conf.POLICY_NAME, pol)
                    of_values = [
                        (0.0, 1.0),  # of-alpha=0, of-beta=1
                        (1.0, 0.0),  # of-alpha=1, of-beta=0
                    ]

                    for of_alpha, of_beta in of_values:
                        config.set(conf.SEC_POLICY, conf.ALPHA, str(of_alpha))
                        config.set(conf.SEC_POLICY, conf.BETA, str(of_beta))

                        keys = {
                            "Policy": pol,
                            "Budget": budget,
                            "Seed": seed,
                            "Variant_mode": variant_mode,
                            "OF-Alpha": of_alpha,
                            "OF-Beta": of_beta,

                        }

                        run_string = "_".join([f"{k}{v}" for k, v in keys.items()])

                        # Check if we can skip this run
                        if old_results is not None and not old_results[

                            (old_results.Policy == pol) &
                            (old_results.Budget == budget) &
                            (old_results.Seed == seed) &
                            (old_results.Variant_mode == variant_mode) &
                            (old_results["OF-Alpha"] == of_alpha) &
                            (old_results["OF-Beta"] == of_beta)
                        ].empty:
                            print("Skipping conf")
                            continue

                        seed_sequence = SeedSequence(seed)
                        rng = default_rng(seed_sequence.spawn(1)[0])
                        temp_spec_file = generate_random_temp_spec_variants(
                            rng, variants_mode=variant_mode, arrivals_to_single_node=False,
                            cloud_cost_reg_a=COST_REG_CLOUD_HIGH, cloud_cost_reg_b=COST_REG_CLOUD_LOW
                        )
                        infra = default_infra(is_edge_green=True)
                        stats = _experiment(config, seed_sequence, infra, temp_spec_file.name)
                        temp_spec_file.close()

                        with open(os.path.join(results_directory, f"{exp_tag}_{run_string}.json"), "w") as of:
                            stats.print(of)

                        result = dict(list(keys.items()) + list(relevant_stats_dict(stats).items()))
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

    with open(os.path.join(results_directory, f"{exp_tag}_conf.ini"), "w") as of:
        config.write(of)

def experiment_main_comparison_green_greedy(args, config, seeds, flag_seeds):
    results = []
    exp_tag = "mainComparisonGreen_Greedy"+ "_" + flag_seeds
    config.set(conf.SEC_POLICY, conf.SPLIT_BUDGET_AMONG_EDGE_NODES, "false")
    results_directory = DEFAULT_OUT_DIR + "_results_greedy"
    os.makedirs(results_directory, exist_ok=True)
    outfile = os.path.join(results_directory, f"{exp_tag}.csv")

    config.set(conf.SEC_POLICY, conf.POLICY_UPDATE_INTERVAL, "600")
    config.set(conf.SEC_POLICY, conf.POLICY_ARRIVAL_RATE_ALPHA, "0.3")

    POLICIES = ["greedy-multi-region",
                "greedy-carbon-aware",
                "greedy-carbon-aware-strict"]

    # Check existing results
    old_results = None
    if not args.force:
        try:
            old_results = pd.read_csv(outfile)
        except:
            pass

    variants_mode = [0,1] #variants mode: 0 inactive, 1 active with speedup=utility for each variants

    for seed in seeds:
        config.set(conf.SEC_SIM, conf.SEED, str(seed))
        for budget in BUDGETS:
            config.set(conf.SEC_POLICY, conf.HOURLY_BUDGET, str(budget))
            for variant_mode in variants_mode:
                for pol in POLICIES:
                    config.set(conf.SEC_POLICY, conf.POLICY_NAME, pol)

                    keys = {
                        "Policy": pol,
                        "Budget": budget,
                        "Seed": seed,
                        "Variant_mode": variant_mode
                    }

                    run_string = "_".join([f"{k}{v}" for k, v in keys.items()])

                    # Check if we can skip this run
                    if old_results is not None and not old_results[
                       (old_results.Policy == pol) &
                       (old_results.Budget == budget) &
                        (old_results.Seed == seed) &
                        (old_results.Variant_mode == variant_mode)
                    ].empty:
                        print("Skipping conf")
                        continue

                    seed_sequence = SeedSequence(seed)
                    rng = default_rng(seed_sequence.spawn(1)[0])
                    temp_spec_file = generate_random_temp_spec_variants(
                        rng, variants_mode=variant_mode, arrivals_to_single_node=False,
                        cloud_cost_reg_a=COST_REG_CLOUD_HIGH, cloud_cost_reg_b=COST_REG_CLOUD_LOW
                    )
                    infra = default_infra(is_edge_green=True)
                    stats = _experiment(config, seed_sequence, infra, temp_spec_file.name)
                    temp_spec_file.close()

                    with open(os.path.join(results_directory, f"{exp_tag}_{run_string}.json"), "w") as of:
                        stats.print(of)

                    result = dict(list(keys.items()) + list(relevant_stats_dict(stats).items()))
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

    with open(os.path.join(results_directory, f"{exp_tag}_conf.ini"), "w") as of:
        config.write(of)


def experiment_main_comparison_green_baseline(args, config, seeds, flag_seeds):
    results = []
    exp_tag = "mainComparisonGreen_Baseline"+ "_" + flag_seeds
    config.set(conf.SEC_POLICY, conf.SPLIT_BUDGET_AMONG_EDGE_NODES, "false")
    results_directory = DEFAULT_OUT_DIR + "_results_baseline"
    os.makedirs(results_directory, exist_ok=True)
    outfile = os.path.join(results_directory, f"{exp_tag}.csv")

    config.set(conf.SEC_POLICY, conf.POLICY_UPDATE_INTERVAL, "600")
    config.set(conf.SEC_POLICY, conf.POLICY_ARRIVAL_RATE_ALPHA, "0.3")

    POLICIES = ["random-multi-region","random-multi-region-no-drop",
                "basic-multi-region"]

    # Check existing results
    old_results = None
    if not args.force:
        try:
            old_results = pd.read_csv(outfile)
        except:
            pass

    variants_mode = [0,1] #variants mode: 0 inactive, 1 active with speedup=utility for each variants

    for seed in seeds:
        config.set(conf.SEC_SIM, conf.SEED, str(seed))
        for budget in BUDGETS:
            config.set(conf.SEC_POLICY, conf.HOURLY_BUDGET, str(budget))
            for variant_mode in variants_mode:
                for pol in POLICIES:
                    config.set(conf.SEC_POLICY, conf.POLICY_NAME, pol)

                    keys = {
                        "Policy": pol,
                        "Budget": budget,
                        "Seed": seed,
                        "Variant_mode": variant_mode
                    }

                    run_string = "_".join([f"{k}{v}" for k, v in keys.items()])

                    # Check if we can skip this run
                    if old_results is not None and not old_results[
                       (old_results.Policy == pol) &
                       (old_results.Budget == budget) &
                        (old_results.Seed == seed) &
                        (old_results.Variant_mode == variant_mode)
                    ].empty:
                        print("Skipping conf")
                        continue

                    seed_sequence = SeedSequence(seed)
                    rng = default_rng(seed_sequence.spawn(1)[0])
                    temp_spec_file = generate_random_temp_spec_variants(
                        rng, variants_mode=variant_mode, arrivals_to_single_node=False,
                        cloud_cost_reg_a=COST_REG_CLOUD_HIGH, cloud_cost_reg_b=COST_REG_CLOUD_LOW
                    )
                    infra = default_infra(is_edge_green=True)
                    stats = _experiment(config, seed_sequence, infra, temp_spec_file.name)
                    temp_spec_file.close()

                    with open(os.path.join(results_directory, f"{exp_tag}_{run_string}.json"), "w") as of:
                        stats.print(of)

                    result = dict(list(keys.items()) + list(relevant_stats_dict(stats).items()))
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

    with open(os.path.join(results_directory, f"{exp_tag}_conf.ini"), "w") as of:
        config.write(of)


def experiment_main_comparison_green_normalized(args, config, seeds, flag_seeds):
    results = []
    exp_tag = "mainComparisonGreen_normalized"+ "_" + flag_seeds
    config.set(conf.SEC_POLICY, conf.SPLIT_BUDGET_AMONG_EDGE_NODES, "false")
    results_directory = DEFAULT_OUT_DIR + "_results_probabilistic"
    os.makedirs(results_directory, exist_ok=True)
    outfile = os.path.join(results_directory, f"{exp_tag}.csv")

    config.set(conf.SEC_POLICY, conf.POLICY_UPDATE_INTERVAL, "600")
    config.set(conf.SEC_POLICY, conf.POLICY_ARRIVAL_RATE_ALPHA, "0.3")

    POLICIES = ["probabilistic-carbon-aware"]

    # Check existing results
    old_results = None
    if not args.force:
        try:
            old_results = pd.read_csv(outfile)
        except:
            pass

    variants_mode = [0,1] #variants mode: 0 inactive, 1 active with speedup=utility for each variants

    for seed in seeds:
        config.set(conf.SEC_SIM, conf.SEED, str(seed))
        for budget in BUDGETS:
            config.set(conf.SEC_POLICY, conf.HOURLY_BUDGET, str(budget))
            for variant_mode in variants_mode:
                for pol in POLICIES:
                    config.set(conf.SEC_POLICY, conf.POLICY_NAME, pol)
                    of_values = [
                        (0.5, 0.5),  # of-alpha=0, of-beta=1
                    ]

                    for of_alpha, of_beta in of_values:
                        config.set(conf.SEC_POLICY, conf.ALPHA, str(of_alpha))
                        config.set(conf.SEC_POLICY, conf.BETA, str(of_beta))

                        keys = {
                            "Policy": pol,
                            "Budget": budget,
                            "Seed": seed,
                            "Variant_mode": variant_mode,
                            "OF-Alpha": of_alpha,
                            "OF-Beta": of_beta,

                        }

                        run_string = "_".join([f"{k}{v}" for k, v in keys.items()])

                        # Check if we can skip this run
                        if old_results is not None and not old_results[

                            (old_results.Policy == pol) &
                            (old_results.Budget == budget) &
                            (old_results.Seed == seed) &
                            (old_results.Variant_mode == variant_mode) &
                            (old_results["OF-Alpha"] == of_alpha) &
                            (old_results["OF-Beta"] == of_beta)
                        ].empty:
                            print("Skipping conf")
                            continue

                        seed_sequence = SeedSequence(seed)
                        rng = default_rng(seed_sequence.spawn(1)[0])
                        temp_spec_file = generate_random_temp_spec_variants(
                            rng, variants_mode=variant_mode, arrivals_to_single_node=False,
                            cloud_cost_reg_a=COST_REG_CLOUD_HIGH, cloud_cost_reg_b=COST_REG_CLOUD_LOW
                        )
                        infra = default_infra(is_edge_green=True)
                        stats = _experiment(config, seed_sequence, infra, temp_spec_file.name)
                        temp_spec_file.close()

                        with open(os.path.join(results_directory, f"{exp_tag}_{run_string}.json"), "w") as of:
                            stats.print(of)

                        result = dict(list(keys.items()) + list(relevant_stats_dict(stats).items()))
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

    with open(os.path.join(results_directory, f"{exp_tag}_conf.ini"), "w") as of:
        config.write(of)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment', action='store', required=False, default="", type=str)
    parser.add_argument('--force', action='store_true', required=False, default=False)
    parser.add_argument('--debug', action='store_true', required=False, default=False)
    parser.add_argument('--seed', action='store', required=False, default=None, type=int)

    args = parser.parse_args()

    config = conf.parse_config_file("config.ini")
    config.set(conf.SEC_SIM, conf.STAT_PRINT_INTERVAL, "-1")
    config.set(conf.SEC_SIM, conf.CLOSE_DOOR_TIME, str(DEFAULT_DURATION))

    os.makedirs(DEFAULT_OUT_DIR, exist_ok=True)

    flag_1half = "1half"
    flag_2half = "2half"

    # BROWN SCENARIO source green_env/bin/activate
    if args.experiment.lower() == "brown_probabilistic_1half":  #sess1 python3 experiments_carbon_awareness.py --experiment brown_probabilistic_1half
        SEEDS = [1, 293, 287844, 2902, 944]
        experiment_main_comparison_brown(args, config, SEEDS, flag_1half)
    elif args.experiment.lower() == "brown_probabilistic_2half":    #sess2 python3 experiments_carbon_awareness.py --experiment brown_probabilistic_2half
        SEEDS = [9573, 102903, 193, 456, 71]
        experiment_main_comparison_brown(args, config, SEEDS, flag_2half)
    elif args.experiment.lower() == "brown_baseline_1half": #sess3 python3 experiments_carbon_awareness.py --experiment brown_baseline_1half
        SEEDS = [1, 293, 287844, 2902, 944]
        experiment_main_comparison_brown_baseline(args, config, SEEDS, flag_1half)  #python3 experiments_carbon_awareness.py --experiment brown_baseline_2half
    elif args.experiment.lower() == "brown_baseline_2half": #sess4
        SEEDS = [9573, 102903, 193, 456, 71]
        experiment_main_comparison_brown_baseline(args, config, SEEDS, flag_2half)
    elif args.experiment.lower() == "brown_greedy_1half":   #sess5 python3 experiments_carbon_awareness.py --experiment brown_greedy_1half
        SEEDS = [1, 293, 287844, 2902, 944]
        experiment_main_comparison_brown_greedy(args, config, SEEDS, flag_1half)    #python3 experiments_carbon_awareness.py --experiment brown_greedy_2half
    elif args.experiment.lower() == "brown_greedy_2half":   #sess6
        SEEDS = [9573, 102903, 193, 456, 71]
        experiment_main_comparison_brown_greedy(args, config, SEEDS, flag_2half)
    elif args.experiment.lower() == "brown_probabilistic_norm_1half":   #sess7   python3 experiments_carbon_awareness.py --experiment brown_probabilistic_norm_1half
        SEEDS = [1, 293, 287844, 2902, 944]
        experiment_main_comparison_brown_normalized(args, config, SEEDS, flag_1half)
    elif args.experiment.lower() == "brown_probabilistic_norm_2half":   #sess8 python3 experiments_carbon_awareness.py --experiment brown_probabilistic_norm_2half
        SEEDS = [9573, 102903, 193, 456, 71]
        experiment_main_comparison_brown_normalized(args, config, SEEDS, flag_2half)    #stopped

    #GREEN SCENARIO
    elif args.experiment.lower() == "green_probabilistic_1half":    #sess11 source green_env/bin/activate
        SEEDS = [1, 293, 287844, 2902, 944]
        experiment_main_comparison_green(args, config, SEEDS, flag_1half)
    elif args.experiment.lower() == "green_probabilistic_2half":    #sess12
        SEEDS = [9573, 102903, 193, 456, 71]
        experiment_main_comparison_green(args, config, SEEDS, flag_2half)
    elif args.experiment.lower() == "green_baseline_1half":     #sess13
        SEEDS = [1, 293, 287844, 2902, 944]
        experiment_main_comparison_green_baseline(args, config, SEEDS, flag_1half)
    elif args.experiment.lower() == "green_baseline_2half":     #sess14
        SEEDS = [9573, 102903, 193, 456, 71]
        experiment_main_comparison_green_baseline(args, config, SEEDS, flag_2half) #stopped
    elif args.experiment.lower() == "green_greedy_1half":       #sess15
        SEEDS = [1, 293, 287844, 2902, 944]
        experiment_main_comparison_green_greedy(args, config, SEEDS, flag_1half)
    elif args.experiment.lower() == "green_greedy_2half":       #sess16
        SEEDS = [9573, 102903, 193, 456, 71]
        experiment_main_comparison_green_greedy(args, config, SEEDS, flag_2half)    #stopped
    elif args.experiment.lower() == "green_probabilistic_norm_1half":   #sess17
        SEEDS = [1, 293, 287844, 2902, 944]
        experiment_main_comparison_green_normalized(args, config, SEEDS, flag_1half)
    elif args.experiment.lower() == "green_probabilistic_norm_2half":   #sess18
        SEEDS = [9573, 102903, 193, 456, 71]
        experiment_main_comparison_green_normalized(args, config, SEEDS, flag_2half)    #stopped

    else:
        print("Unknown experiment!")
        exit(1)


