import sys
import tempfile
import os
import argparse
import pandas as pd
import numpy as np
import yaml

import conf
from spec import generate_regions_yaml, generate_random_temp_spec_variants
from simulation import Simulation
from infrastructure import *
from main import read_spec_file
from numpy.random import SeedSequence, default_rng

DEFAULT_CONFIG_FILE = "config.ini"
DEFAULT_OUT_DIR = "200125_results"
DEFAULT_OUT_DIR_CO2_TRACKING = "200125_results/green_co2_tracking"
DEFAULT_DURATION = 10000000
SEEDS=[1,293,287844,2902,944,9573,102903,193,456,71]
PERCENTILES=np.array([1,5,10,25,50,75,90,95,99])/100.0


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

def default_infra(edge_cloud_latency=0.100, is_edge_green=True):
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
    result["EnergyConsNode"] = stats.energy_consumption_per_node
    result["EnergyConsTotal"] = stats.energy_consumption_total

    #result["CO2EmissNode"] = stats.co2_emission_per_node
    result["TotalProcTime"] = stats.total_processing_time
    #result["CO2EmissFuncNode"] = stats.co2_emission_function2node
    result["CO2EmissTotal"] = stats.co2_emission_total
    return result


def experiment_main_comparison_green(args, config):
    results = []
    exp_tag = "mainComparisonGreen"
    config.set(conf.SEC_POLICY, conf.SPLIT_BUDGET_AMONG_EDGE_NODES, "false")
    outfile = os.path.join(DEFAULT_OUT_DIR, f"{exp_tag}.csv")

    #config.set(conf.SEC_POLICY, conf.CLOUD_COLD_START_EST_STRATEGY, "pacs")
    #config.set(conf.SEC_POLICY, conf.EDGE_COLD_START_EST_STRATEGY, "pacs")
    config.set(conf.SEC_POLICY, conf.POLICY_UPDATE_INTERVAL, "600")
    config.set(conf.SEC_POLICY, conf.POLICY_ARRIVAL_RATE_ALPHA, "0.3")

    POLICIES = ["random-multi-region",
                "basic-multi-region",
        "probabilistic-carbon-aware"
    ]

    # Check existing results
    old_results = None
    if not args.force:
        try:
            old_results = pd.read_csv(outfile)
        except:
            pass

    variants_mode = [0,1,2] #variants mode: 0 inactive, 1 active with speedup=utility for each variants, 2 active with speedup!=utility

    for seed in SEEDS:
        config.set(conf.SEC_SIM, conf.SEED, str(seed))
        seed_sequence = SeedSequence(seed)
        for budget in [0.5, 2, 20, 50]:
            config.set(conf.SEC_POLICY, conf.HOURLY_BUDGET, str(budget))
            for variant_mode in variants_mode:
                for pol in POLICIES:
                    config.set(conf.SEC_POLICY, conf.POLICY_NAME, pol)
                    if pol == "probabilistic-carbon-aware":

                        # Handle "probabilistic-carbon-aware" policy with an additional inner loop

                        of_values = [
                            (0.0, 1.0),  # of-alpha=0, of-beta=1
                            (1.0, 0.0),  # of-alpha=1, of-beta=0
                            (0.5, 0.5),  # of-alpha=0.5, of-beta=0.5
                            (0.3, 0.7),  # of-alpha=0.5, of-beta=0.5
                            (0.7, 0.3),  # of-alpha=0.5, of-beta=0.5
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
                            filename_res = os.path.join(DEFAULT_OUT_DIR_CO2_TRACKING, f"{exp_tag}_{run_string}.csv")
                            #print("in experiments: run_string: ", run_string)
                            #print("in experiments: filename_res: ", filename_res)
                            config.set(conf.SEC_CARBON, conf.FILE_UPDATE_CO2_INTENSITY, str(filename_res))
                            #print("in experiments: conf: ", config.get(conf.SEC_CARBON, conf.FILE_UPDATE_CO2_INTENSITY))

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

                            rng = default_rng(seed_sequence.spawn(1)[0])
                            #rng = SeedSequence(seed)
                            temp_spec_file = generate_random_temp_spec_variants(
                                rng, variants_mode=variant_mode, arrivals_to_single_node=False,
                                cloud_cost_reg_a=0.00001, cloud_cost_reg_b=0.00003
                            )
                            infra = default_infra(is_edge_green=True)
                            stats = _experiment(config, seed_sequence, infra, temp_spec_file.name)
                            temp_spec_file.close()

                            with open(os.path.join(DEFAULT_OUT_DIR, f"{exp_tag}_{run_string}.json"), "w") as of:
                                stats.print(of)

                            result = dict(list(keys.items()) + list(relevant_stats_dict(stats).items()))
                            results.append(result)
                            print(result)

                            resultsDf = pd.DataFrame(results)
                            if old_results is not None:
                                resultsDf = pd.concat([old_results, resultsDf])
                            resultsDf.to_csv(outfile, index=False)

                    else:

                        keys = {
                            "Policy": pol,
                            "Budget": budget,
                            "Seed": seed,
                            "Variant_mode": variant_mode
                        }

                        run_string = "_".join([f"{k}{v}" for k, v in keys.items()])
                        filename_res = os.path.join(DEFAULT_OUT_DIR_CO2_TRACKING, f"{exp_tag}_{run_string}.csv")
                        print("in experiments: run_string: ", run_string)
                        print("in experiments: filename_res: ", filename_res)
                        config.set(conf.SEC_CARBON, conf.FILE_UPDATE_CO2_INTENSITY, str(filename_res))
                        print("in experiments: conf: ", config.get(conf.SEC_CARBON, conf.FILE_UPDATE_CO2_INTENSITY))

                        # Check if we can skip this run
                        if old_results is not None and not old_results[
                           (old_results.Policy == pol) &
                           (old_results.Budget == budget) &
                            (old_results.Seed == seed) &
                            (old_results.Variant_mode == variant_mode)
                        ].empty:
                            print("Skipping conf")
                            continue

                        rng = default_rng(seed_sequence.spawn(1)[0])
                        temp_spec_file = generate_random_temp_spec_variants(
                            rng, variants_mode=variant_mode, arrivals_to_single_node=False,
                            cloud_cost_reg_a=0.001, cloud_cost_reg_b=0.00001
                        )
                        infra = default_infra(is_edge_green=True)
                        stats = _experiment(config, seed_sequence, infra, temp_spec_file.name)
                        temp_spec_file.close()

                        with open(os.path.join(DEFAULT_OUT_DIR, f"{exp_tag}_{run_string}.json"), "w") as of:
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
    #print(resultsDf.groupby("Policy").mean())

    with open(os.path.join(DEFAULT_OUT_DIR, f"{exp_tag}_conf.ini"), "w") as of:
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
    #config.set(conf.SEC_SIM, conf.CLOSE_DOOR_TIME, str(DEFAULT_DURATION))

    if args.debug:
        args.force = True
        SEEDS=SEEDS[:1]

    if args.seed is not None:
        SEEDS = [int(args.seed)]

    experiment_main_comparison_green(args, config)


