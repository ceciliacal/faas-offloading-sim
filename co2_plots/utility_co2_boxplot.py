import csv
import math
import re
import os
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from fontTools.misc.cython import returns
from matplotlib.ticker import MaxNLocator, AutoMinorLocator, MultipleLocator, ScalarFormatter, FixedLocator, \
    FormatStrFormatter

import conf_plots as cp
from matplotlib.patches import Patch

node_colors_brown_scenario = {
    "cloud_region_a": "saddlebrown",
    "cloud_region_b": "seagreen",
    "cloud_region_c": "sandybrown",
    "edge_zone": "burlywood",
    "variant": "navajowhite",
}

node_colors_green_scenario = {
    "cloud_region_a": "seagreen",
    "cloud_region_b": "saddlebrown",
    "cloud_region_c": "sandybrown",
    "edge_zone": "darkseagreen",
    "variant": "palegoldenrod",

}

regions = ["cloud_region_a", "cloud_region_b", "cloud_region_c"]

def plot_bar_with_policy_no_var(input_file_name, output_folder_rel):
    csv_file = os.path.join(os.path.dirname(__file__), input_file_name)
    os.makedirs(output_folder_rel, exist_ok=True)
    data = pd.read_csv(csv_file)

    groups = data.groupby([cp.BUDGET, cp.VAR_MODE])

    if "brown" in output_folder_rel:
        region_colors = node_colors_brown_scenario
    else:
        region_colors = node_colors_green_scenario

    cloud_nodes = {}
    cloud_nodes_a = ["cloud_node_a"]
    cloud_nodes_b = ["cloud_node_b"]
    cloud_nodes_c = ["cloud_node_c"]

    for region in regions:
        for i in range(1, 7):
            node = cloud_nodes_a[0] + (str(i))
            cloud_nodes_a.append(node)
        cloud_nodes[region] = cloud_nodes_a

        for i in range(1, 7):
            node = cloud_nodes_b[0] + (str(i))
            cloud_nodes_b.append(node)
        cloud_nodes[region] = cloud_nodes_b

        for i in range(1, 7):
            node = cloud_nodes_c[0] + (str(i))
            cloud_nodes_c.append(node)
        cloud_nodes[region] = cloud_nodes_c

    for (budget, variant_mode), group_data in groups:
        plot_data = {}

        for policy in group_data[cp.POLICY].unique():
            if policy == "probabilistic-carbon-aware":
                grouped_by_policy = group_data[group_data[cp.POLICY] == policy].groupby([cp.ALPHA, cp.BETA])
                for (alpha, beta), sub_group in grouped_by_policy:
                    new_policy_name = f"{policy} ({alpha},{beta})"
                    plot_data[new_policy_name] = sub_group
            else:
                plot_data[policy] = group_data[group_data[cp.POLICY] == policy]

        # Prepare figure
        fig, ax = plt.subplots(figsize=(12, 6.5))
        width = 0.2  # Wider bars for better stacking visualization
        spacing = 0.5  # More spacing between policies

        x_positions = []
        x_labels_completion = []
        policy_tick_positions = []
        policy_labels_list = []

        for i, (policy_name, sub_group) in enumerate(plot_data.items()):
            completions = []

            for _, row in sub_group.iterrows():
                try:
                    completion_json = json.loads(row[cp.COMPLETIONS_DISTRIBUTION])
                    all_nodes = [k for k in completion_json.keys() if "dispatcher" not in k]

                except (json.JSONDecodeError, KeyError):
                    continue  # Skip invalid JSON entries

                completion_values = {
                    node_name: {"(f,s)": 0, "(f,c)": 0, "(v,s)": 0, "(v,c)": 0}
                    for node_name in all_nodes
                }

                for node, node_data in completion_json.items():
                    if node in all_nodes:#mettere ttti nodi qui!
                        completion_values[node]["(f,s)"] = node_data["total"]["standard"]
                        completion_values[node]["(f,c)"] = node_data["total"]["critical"]
                        if variant_mode == 1:
                            completion_values[node]["(v,s)"] = node_data["variants"]["standard"]
                            completion_values[node]["(v,c)"] = node_data["variants"]["critical"]

                completions.append(completion_values)

            if not completions:
                continue

            # Aggregate values for the policy
            aggregated_values = {
                "(f,s)": {node: sum(c[node]["(f,s)"] for c in completions) for node in all_nodes},
                "(f,c)": {node: sum(c[node]["(f,c)"] for c in completions) for node in all_nodes},
                "(v,s)": {node: sum(c[node]["(v,s)"] for c in completions) for node in all_nodes},
                "(v,c)": {node: sum(c[node]["(v,c)"] for c in completions) for node in all_nodes}
            }

            # X-tick positions for this policy
            bar_positions = np.array([i * spacing, i * spacing + width])  # Two bars per policy
            x_positions.extend(bar_positions)
            x_labels_completion.extend(["Standard", "Critical"])

            # Store center position for policy label
            policy_tick_positions.append(np.mean(bar_positions))
            policy_label = policy_labels_dict.get(policy_name, policy_name)
            policy_labels_list.append(policy_label)

            # ————————————————————————————————————————
            # 1) Define which keys are clouds vs edges
            edge_nodes = [n for n in all_nodes if "edge" in n]

            # 2) Sum up f,s and f,c for each group
            for i in range(0,7):
                fs_cloud_a = aggregated_values["(f,s)"][cloud_nodes_a[i]]
                fs_cloud_b = aggregated_values["(f,s)"][cloud_nodes_b[i]]
                fs_cloud_c = aggregated_values["(f,s)"][cloud_nodes_c[i]]

                fc_cloud_a = aggregated_values["(f,c)"][cloud_nodes_a[i]]
                fc_cloud_b = aggregated_values["(f,c)"][cloud_nodes_b[i]]
                fc_cloud_c = aggregated_values["(f,c)"][cloud_nodes_c[i]]
            fs_edge = sum(aggregated_values["(f,s)"][n] for n in edge_nodes)
            fc_edge = sum(aggregated_values["(f,c)"][n] for n in edge_nodes)

            # 3) Sum up v,s and v,c for edges only (cloud variants assumed zero)
            if variant_mode == 1:
                vs_edge = sum(aggregated_values["(v,s)"][n] for n in edge_nodes)
                vc_edge = sum(aggregated_values["(v,c)"][n] for n in edge_nodes)
            else:
                vs_edge = vc_edge = 0

            # pick one of the edge colors to use for the whole zone
            edge_color = next((v for k, v in region_colors.items() if "edge" in k), None)
            variant_color = next((v for k, v in region_colors.items() if "variant" in k), None)

            # — plot the STANDARD bar (bar_positions[0]) —
            bottom = 0
            SCALE = 1e7

            # Cloud A
            ax.bar(bar_positions[0],
                   fs_cloud_a / SCALE,
                   width,
                   color=region_colors["cloud_region_a"],
                   edgecolor="black")
            bottom += fs_cloud_a / SCALE

            # Cloud B
            ax.bar(bar_positions[0],
                   fs_cloud_b / SCALE,
                   width,
                   color=region_colors["cloud_region_b"],
                   edgecolor="black",
                   bottom=bottom)
            bottom += fs_cloud_b / SCALE

            ax.bar(bar_positions[0],
                   fs_cloud_c / SCALE,
                   width,
                   color=region_colors["cloud_region_c"],
                   edgecolor="black",
                   bottom=bottom)
            bottom += fs_cloud_c / SCALE

            # Edge Zone (no variants)
            ax.bar(bar_positions[0],
                   fs_edge / SCALE,
                   width,
                   color=edge_color,
                   edgecolor="black",
                   bottom=bottom)
            bottom += fs_edge / SCALE

            # Function Variant (hatched)
            if variant_mode == 1:
                ax.bar(bar_positions[0],
                       vs_edge / SCALE,
                       width,
                       color=variant_color,
                       edgecolor="black",
                       hatch="x",
                       bottom=bottom / SCALE)

            # — plot the CRITICAL bar (bar_positions[1]) —
            bottom = 0
            ax.bar(bar_positions[1],
                   fc_cloud_a / SCALE,
                   width,
                   color=region_colors["cloud_region_a"],
                   edgecolor="black")
            bottom += fc_cloud_a / SCALE

            ax.bar(bar_positions[1],
                   fc_cloud_b / SCALE,
                   width,
                   color=region_colors["cloud_region_b"],
                   edgecolor="black",
                   bottom=bottom)
            bottom += fc_cloud_b / SCALE

            ax.bar(bar_positions[1],
                   fc_cloud_c / SCALE,
                   width,
                   color=region_colors["cloud_region_c"],
                   edgecolor="black",
                   bottom=bottom)
            bottom += fc_cloud_c / SCALE

            ax.bar(bar_positions[1],
                   fc_edge / SCALE,
                   width,
                   color=edge_color,
                   edgecolor="black",
                   bottom=bottom)
            bottom += fc_edge / SCALE

            if variant_mode == 1:
                ax.bar(bar_positions[1],
                       vc_edge / SCALE,
                       width,
                       color=variant_color,
                       edgecolor="black",
                       hatch="x",
                       bottom=bottom  / SCALE)

            # — rebuild a 4-entry legend —
            legend_handles = [
                Patch(facecolor=region_colors["cloud_region_a"], edgecolor="black", label="Cloud region A"),
                Patch(facecolor=region_colors["cloud_region_b"], edgecolor="black", label="Cloud region B"),
                Patch(facecolor=region_colors["cloud_region_c"], edgecolor="black", label="Cloud region C"),
                Patch(facecolor=edge_color, edgecolor="black", label="Edge Zone - no Var"),
            ]
            if variant_mode == 1:
                legend_handles.append(
                    Patch(facecolor=variant_color, edgecolor="black", hatch="x", label="Edge Zone - with Var")
                )

            ax.legend(
                handles=legend_handles,
                #loc="upper right",  # position legend at upper right inside the axes
                #bbox_to_anchor=(0.98, 0.98),  # slight inset from the very corner
                frameon=True,
                edgecolor="black",
                title="Legend",
                fontsize=18
            )

            # ————————————————————————————————————————

        # Set x-axis labels (First level: Closest to bars)
        ax.set_xticks(x_positions)
        ax.set_xticklabels(x_labels_completion, rotation=0, ha="center", fontsize=20)

        # Add second-level x labels (Policies BELOW the first labels)
        for pos, policy in zip(policy_tick_positions, policy_labels_list):
            ax.text(pos,
                    -0.08,  # 8% below the x-axis
                    policy,
                    ha='center',
                    va='top',
                    fontsize=22,
                    transform=ax.get_xaxis_transform())  # interpret y in axis coords

        ax.set_ylabel("Number of Completed Requests (10⁷)", fontsize=22)
        sf = ScalarFormatter(useMathText=False)  # set True if you want ×10^3 style
        sf.set_scientific(True)
        sf.set_powerlimits((7, 7))  # force 10^3
        ax.yaxis.set_major_formatter(FormatStrFormatter('%.1f'))
        ax.tick_params(axis='y', labelsize=18)

        plt.subplots_adjust(right=0.8, bottom=0.2)  # Extend space (increase if needed)

        output_path = os.path.join(output_folder_rel, f"completion_{budget}_{variant_mode}.png")
        plt.tight_layout()
        plt.savefig(output_path)
        plt.show()
        plt.close()

def plot_bar(input_file_name, output_folder_rel):
    csv_file = os.path.join(os.path.dirname(__file__), input_file_name)
    os.makedirs(output_folder_rel, exist_ok=True)
    data = pd.read_csv(csv_file)

    groups = data.groupby([cp.BUDGET, cp.VAR_MODE])

    if "brown" in output_folder_rel:
        region_colors = node_colors_brown_scenario
    else:
        region_colors = node_colors_green_scenario

    cloud_nodes = {}
    cloud_nodes_a = ["cloud_node_a"]
    cloud_nodes_b = ["cloud_node_b"]
    cloud_nodes_c = ["cloud_node_c"]

    for region in regions:
        for i in range(1, 7):
            node = cloud_nodes_a[0] + (str(i))
            cloud_nodes_a.append(node)
        cloud_nodes[region] = cloud_nodes_a

        for i in range(1, 7):
            node = cloud_nodes_b[0] + (str(i))
            cloud_nodes_b.append(node)
        cloud_nodes[region] = cloud_nodes_b

        for i in range(1, 7):
            node = cloud_nodes_c[0] + (str(i))
            cloud_nodes_c.append(node)
        cloud_nodes[region] = cloud_nodes_c

    for (budget, variant_mode), group_data in groups:
        plot_data = {}

        for policy in group_data[cp.POLICY].unique():
            if policy == "probabilistic-carbon-aware":
                grouped_by_policy = group_data[group_data[cp.POLICY] == policy].groupby([cp.ALPHA, cp.BETA])
                for (alpha, beta), sub_group in grouped_by_policy:
                    new_policy_name = f"{policy} ({alpha},{beta})"
                    plot_data[new_policy_name] = sub_group
            else:
                plot_data[policy] = group_data[group_data[cp.POLICY] == policy]

        # Prepare figure
        fig, ax = plt.subplots(figsize=(12, 6.5))
        width = 0.2  # Wider bars for better stacking visualization
        spacing = 0.5  # More spacing between policies

        x_positions = []
        x_labels_completion = []
        policy_tick_positions = []
        policy_labels_list = []

        for i, (policy_name, sub_group) in enumerate(plot_data.items()):
            completions = []

            for _, row in sub_group.iterrows():
                try:
                    completion_json = json.loads(row[cp.COMPLETIONS_DISTRIBUTION])
                    all_nodes = [k for k in completion_json.keys() if "dispatcher" not in k]

                except (json.JSONDecodeError, KeyError):
                    continue  # Skip invalid JSON entries

                completion_values = {
                    node_name: {"(f,s)": 0, "(f,c)": 0, "(v,s)": 0, "(v,c)": 0}
                    for node_name in all_nodes
                }

                for node, node_data in completion_json.items():
                    if node in all_nodes:#mettere ttti nodi qui!
                        completion_values[node]["(f,s)"] = node_data["total"]["standard"]
                        completion_values[node]["(f,c)"] = node_data["total"]["critical"]
                        if variant_mode == 1:
                            completion_values[node]["(v,s)"] = node_data["variants"]["standard"]
                            completion_values[node]["(v,c)"] = node_data["variants"]["critical"]

                completions.append(completion_values)

            if not completions:
                continue

            # Aggregate values for the policy
            aggregated_values = {
                "(f,s)": {node: sum(c[node]["(f,s)"] for c in completions) for node in all_nodes},
                "(f,c)": {node: sum(c[node]["(f,c)"] for c in completions) for node in all_nodes},
                "(v,s)": {node: sum(c[node]["(v,s)"] for c in completions) for node in all_nodes},
                "(v,c)": {node: sum(c[node]["(v,c)"] for c in completions) for node in all_nodes}
            }

            # X-tick positions for this policy
            bar_positions = np.array([i * spacing, i * spacing + width])  # Two bars per policy
            x_positions.extend(bar_positions)
            x_labels_completion.extend(["Standard", "Critical"])

            # Store center position for policy label
            policy_tick_positions.append(np.mean(bar_positions))
            policy_label = policy_labels_dict.get(policy_name, policy_name)
            policy_labels_list.append(policy_label)

            # ————————————————————————————————————————
            # 1) Define which keys are clouds vs edges
            edge_nodes = [n for n in all_nodes if "edge" in n]

            # 2) Sum up f,s and f,c for each group
            for i in range(0,7):
                fs_cloud_a = aggregated_values["(f,s)"][cloud_nodes_a[i]]
                fs_cloud_b = aggregated_values["(f,s)"][cloud_nodes_b[i]]
                fs_cloud_c = aggregated_values["(f,s)"][cloud_nodes_c[i]]

                fc_cloud_a = aggregated_values["(f,c)"][cloud_nodes_a[i]]
                fc_cloud_b = aggregated_values["(f,c)"][cloud_nodes_b[i]]
                fc_cloud_c = aggregated_values["(f,c)"][cloud_nodes_c[i]]
            fs_edge = sum(aggregated_values["(f,s)"][n] for n in edge_nodes)
            fc_edge = sum(aggregated_values["(f,c)"][n] for n in edge_nodes)

            # 3) Sum up v,s and v,c for edges only (cloud variants assumed zero)
            if variant_mode == 1:
                vs_edge = sum(aggregated_values["(v,s)"][n] for n in edge_nodes)
                vc_edge = sum(aggregated_values["(v,c)"][n] for n in edge_nodes)
            else:
                vs_edge = vc_edge = 0

            # pick one of the edge colors to use for the whole zone
            edge_color = next((v for k, v in region_colors.items() if "edge" in k), None)
            variant_color = next((v for k, v in region_colors.items() if "variant" in k), None)

            # — plot the STANDARD bar (bar_positions[0]) —
            bottom = 0
            SCALE = 1e7

            # Cloud A
            ax.bar(bar_positions[0],
                   fs_cloud_a / SCALE,
                   width,
                   color=region_colors["cloud_region_a"],
                   edgecolor="black")
            bottom += fs_cloud_a / SCALE

            # Cloud B
            ax.bar(bar_positions[0],
                   fs_cloud_b / SCALE,
                   width,
                   color=region_colors["cloud_region_b"],
                   edgecolor="black",
                   bottom=bottom)
            bottom += fs_cloud_b / SCALE

            ax.bar(bar_positions[0],
                   fs_cloud_c / SCALE,
                   width,
                   color=region_colors["cloud_region_c"],
                   edgecolor="black",
                   bottom=bottom)
            bottom += fs_cloud_c / SCALE

            # Edge Zone (no variants)
            ax.bar(bar_positions[0],
                   fs_edge / SCALE,
                   width,
                   color=edge_color,
                   edgecolor="black",
                   bottom=bottom)
            bottom += fs_edge / SCALE

            # Function Variant (hatched)
            if variant_mode == 1:
                ax.bar(bar_positions[0],
                       vs_edge / SCALE,
                       width,
                       color=variant_color,
                       edgecolor="black",
                       hatch="x",
                       bottom=bottom / SCALE)

            # — plot the CRITICAL bar (bar_positions[1]) —
            bottom = 0
            ax.bar(bar_positions[1],
                   fc_cloud_a / SCALE,
                   width,
                   color=region_colors["cloud_region_a"],
                   edgecolor="black")
            bottom += fc_cloud_a / SCALE

            ax.bar(bar_positions[1],
                   fc_cloud_b / SCALE,
                   width,
                   color=region_colors["cloud_region_b"],
                   edgecolor="black",
                   bottom=bottom)
            bottom += fc_cloud_b / SCALE

            ax.bar(bar_positions[1],
                   fc_cloud_c / SCALE,
                   width,
                   color=region_colors["cloud_region_c"],
                   edgecolor="black",
                   bottom=bottom)
            bottom += fc_cloud_c / SCALE

            ax.bar(bar_positions[1],
                   fc_edge / SCALE,
                   width,
                   color=edge_color,
                   edgecolor="black",
                   bottom=bottom)
            bottom += fc_edge / SCALE

            if variant_mode == 1:
                ax.bar(bar_positions[1],
                       vc_edge / SCALE,
                       width,
                       color=variant_color,
                       edgecolor="black",
                       hatch="x",
                       bottom=bottom  / SCALE)

            # — rebuild a 4-entry legend —
            legend_handles = [
                Patch(facecolor=region_colors["cloud_region_a"], edgecolor="black", label="Cloud region A"),
                Patch(facecolor=region_colors["cloud_region_b"], edgecolor="black", label="Cloud region B"),
                Patch(facecolor=region_colors["cloud_region_c"], edgecolor="black", label="Cloud region C"),
                Patch(facecolor=edge_color, edgecolor="black", label="Edge Zone - no Var"),
            ]
            if variant_mode == 1:
                legend_handles.append(
                    Patch(facecolor=variant_color, edgecolor="black", hatch="x", label="Edge Zone - with Var")
                )

            ax.legend(
                handles=legend_handles,
                #loc="upper right",  # position legend at upper right inside the axes
                #bbox_to_anchor=(0.98, 0.98),  # slight inset from the very corner
                frameon=True,
                edgecolor="black",
                title="Legend",
                fontsize=18
            )

            # ————————————————————————————————————————

        # Set x-axis labels (First level: Closest to bars)
        ax.set_xticks(x_positions)
        ax.set_xticklabels(x_labels_completion, rotation=0, ha="center", fontsize=20)

        # Add second-level x labels (Policies BELOW the first labels)
        for pos, policy in zip(policy_tick_positions, policy_labels_list):
            ax.text(pos,
                    -0.08,  # 8% below the x-axis
                    policy,
                    ha='center',
                    va='top',
                    fontsize=22,
                    transform=ax.get_xaxis_transform())  # interpret y in axis coords

        ax.set_ylabel("Number of Completed Requests (10⁷)", fontsize=22)
        sf = ScalarFormatter(useMathText=False)  # set True if you want ×10^3 style
        sf.set_scientific(True)
        sf.set_powerlimits((7, 7))  # force 10^3
        ax.yaxis.set_major_formatter(FormatStrFormatter('%.1f'))
        ax.tick_params(axis='y', labelsize=18)

        plt.subplots_adjust(right=0.8, bottom=0.2)  # Extend space (increase if needed)

        output_path = os.path.join(output_folder_rel, f"completion_{budget}_{variant_mode}.png")
        plt.tight_layout()
        plt.savefig(output_path)
        plt.show()
        plt.close()


def add_QoS_no_var(data, budget, utility_data, cost_budget_data, co2_data, labels):
    #Extract Utility data of "probabilistic-carbon-aware(1.0, 0.0)" WITHOUT variants (VAR_MODE = 0)
    ref_policy_data = data[
        (data[cp.POLICY] == "probabilistic-carbon-aware") &
        (data[cp.ALPHA] == 1.0) & (data[cp.BETA] == 0.0) &
        (data[cp.VAR_MODE] == 0)  # Without variants
    ]
    ref_grouped_by_seed = ref_policy_data[ref_policy_data[cp.BUDGET] == budget].groupby(cp.SEED)
    ref_utility_values = ref_grouped_by_seed[cp.UTILITY].mean().values
    ref_co2_values = ref_grouped_by_seed[cp.CO2_EMISS_TOTAL].mean().values  # Already in 10^3
    ref_cost_budget_percent = (
                                      (ref_grouped_by_seed[cp.COST].mean() / (
                                              ref_grouped_by_seed[cp.TOTAL_PROC_TIME].mean() / 3600))
                                      / (budget * 3)
                              ) * 100  # Compute Cost/Budget %

    # Append reference utility data
    utility_data.append(ref_utility_values)
    cost_budget_data.append(ref_cost_budget_percent)
    co2_data.append(ref_co2_values)
    labels.append("QoS-NV")

   #Extract Utility data of "probabilistic-carbon-aware(0.5, 0.5)" WITHOUT variants (VAR_MODE = 0)
    ref_policy_data = data[
        (data[cp.POLICY] == "probabilistic-carbon-aware") &
        (data[cp.ALPHA] == 0.5) & (data[cp.BETA] == 0.5) &
        (data[cp.VAR_MODE] == 0)  # Without variants
    ]
    ref_grouped_by_seed = ref_policy_data[ref_policy_data[cp.BUDGET] == budget].groupby(cp.SEED)
    ref_utility_values = ref_grouped_by_seed[cp.UTILITY].mean().values
    ref_co2_values = ref_grouped_by_seed[cp.CO2_EMISS_TOTAL].mean().values  # Already in 10^3
    ref_cost_budget_percent = (
                                      (ref_grouped_by_seed[cp.COST].mean() / (
                                              ref_grouped_by_seed[cp.TOTAL_PROC_TIME].mean() / 3600))
                                      / (budget * 3)
                              ) * 100  # Compute Cost/Budget %

    # Append reference utility data
    utility_data.append(ref_utility_values)
    cost_budget_data.append(ref_cost_budget_percent)
    co2_data.append(ref_co2_values)
    labels.append("CO2&QoS-NV")


def reorder_QoS_no_var(utility_data, cost_budget_data, co2_data, labels):
    """
    Reorder entries so that these labels come first in this exact order (if present):
        QoS-NV, QoS, CO2&QoS-NV, CO2&QoS, CO2
    then keep all other labels in their original relative order.

    Assumes labels are unique.
    Modifies lists in place and also returns them.
    """
    desired_prefix = ["QoS-NV", "QoS", "CO2&QoS-NV", "CO2&QoS", "CO2"]

    # Keep all aligned
    rows = list(zip(labels, utility_data, cost_budget_data, co2_data))

    # FIX: unpack lbl from each row
    row_by_label = {lbl: (lbl, u, c, co2) for lbl, u, c, co2 in rows}

    # Put requested labels first (only if present)
    ordered = [row_by_label[lbl] for lbl in desired_prefix if lbl in row_by_label]

    # Append remaining labels preserving original order
    used = set(lbl for lbl, *_ in ordered)
    ordered.extend(row for row in rows if row[0] not in used)

    # Write back in place
    new_labels, new_u, new_c, new_co2 = map(list, zip(*ordered))
    labels[:] = new_labels
    utility_data[:] = new_u
    cost_budget_data[:] = new_c
    co2_data[:] = new_co2

    return utility_data, cost_budget_data, co2_data, labels


def plot_boxplots_cost(input_file_name, output_folder_rel, shape):
    csv_file = os.path.join(os.path.dirname(__file__), input_file_name)
    os.makedirs(output_folder_rel, exist_ok=True)
    data = pd.read_csv(csv_file)

    data = data[(data[cp.POLICY] != 'random-multi-region') & (data[cp.POLICY]!= 'greedy-carbon-aware-strict')]

    # Compute global max values for each type across all scenarios
    global_max_utility = data[cp.UTILITY].max()
    global_max_cost = (data[cp.COST] / (data[cp.TOTAL_PROC_TIME] / 3600) / (data[cp.BUDGET] * 3) * 100).max()
    global_max_co2 = data[cp.CO2_EMISS_TOTAL].max()
    global_min_co2 = data[cp.CO2_EMISS_TOTAL].min()

    # Group by budget and variant mode
    groups = data.groupby([cp.BUDGET, cp.VAR_MODE])

    for (budget, variant_mode), group_data in groups:
        plot_data = {}

        for policy in group_data[cp.POLICY].unique():
            if policy == "probabilistic-carbon-aware":
                grouped_by_policy = group_data[group_data[cp.POLICY] == policy].groupby([cp.ALPHA, cp.BETA])
                for (alpha, beta), sub_group in grouped_by_policy:
                    new_policy_name = f"{policy} ({alpha},{beta})"
                    plot_data[new_policy_name] = sub_group
            else:
                plot_data[policy] = group_data[group_data[cp.POLICY] == policy]
            if policy == "random-multi-region":
                continue
            if policy == "greedy-carbon-aware-strict":
                continue

        utility_data, cost_budget_data, co2_data, labels = [], [], [], []

        #in a scenario with variants, add "probabilistic-carbon-aware(1.0, 0.0)" (no variants)
        if variant_mode != 0:
            add_QoS_no_var(data, budget, utility_data, cost_budget_data, co2_data, labels)

        for policy_name, sub_group in plot_data.items():
            grouped_by_seed = sub_group.groupby(cp.SEED)

            utility_values = grouped_by_seed[cp.UTILITY].mean().values
            co2_values = grouped_by_seed[cp.CO2_EMISS_TOTAL].mean().values  # Already in 10^3
            cost_budget_percent = (
                (grouped_by_seed[cp.COST].mean() / (grouped_by_seed[cp.TOTAL_PROC_TIME].mean() / 3600))
                / (budget * 3)
            ) * 100  # Compute Cost/Budget %

            # Rename policy labels
            policy_label = policy_labels_dict.get(policy_name, policy_name)
            labels.append(policy_label)

            utility_data.append(utility_values)
            cost_budget_data.append(cost_budget_percent.values)
            co2_data.append(co2_values)

        if variant_mode != 0:
            reorder_QoS_no_var(utility_data, cost_budget_data, co2_data, labels)

        # Create plots
        if shape == "h":
            fig, axes = plt.subplots(1, 3, figsize=(30, 12))
        else:
            fig, axes = plt.subplots(3, 1, figsize=(7, 7))

        x_rotation = 43
        tick_fs = 13

        # Utility boxplot
        bp_util = axes[0].boxplot(utility_data, labels=labels, patch_artist=True, showfliers=False)
        for patch, label in zip(bp_util["boxes"], labels):
            patch.set_facecolor(policy_colors.get(label, "black"))
        axes[0].set_ylabel('Utility (10⁶)', size=16)
        #axes[0].set_ylim(0, global_max_utility+global_max_utility * 0.03) #+ (global_max_utility * 0.03))

        axes[0].set_ylim(0, global_max_utility + global_max_utility * 0.03)
        #axes[0].set_ylim(0, 75000000)
        #ymin, ymax = axes[0].get_ylim()
        #axes[0].set_yticks(np.linspace(ymin, ymax, 3))

        axes[0].tick_params(axis='x', rotation=x_rotation, labelsize=tick_fs)
        axes[0].tick_params(axis='y', labelsize=tick_fs)
        axes[0].grid(axis='y', linestyle='--', alpha=0.7)

        # Cost/Budget % boxplot
        bp_cost = axes[1].boxplot(cost_budget_data, labels=labels, patch_artist=True, showfliers=False)
        for patch, label in zip(bp_cost["boxes"], labels):
            patch.set_facecolor(policy_colors.get(label, "black"))

        local_max_cost = max_val = max(v for sub in cost_budget_data for v in sub)
        axes[1].set_ylabel('Cost/Budget (%)', size=16)
        axes[1].set_ylim(0, local_max_cost+ local_max_cost*0.03)
        axes[1].tick_params(axis='x', rotation=x_rotation, labelsize=tick_fs)
        axes[1].tick_params(axis='y', labelsize=tick_fs)
        axes[1].grid(axis='y', linestyle='--', alpha=0.7)
        #axes[1].yaxis.set_major_formatter(FuncFormatter(format_ticks))

        # CO2 Emissions boxplot
        bp_co2 = axes[2].boxplot(co2_data, labels=labels, patch_artist=True, showfliers=False)
        for patch, label in zip(bp_co2["boxes"], labels):
            patch.set_facecolor(policy_colors.get(label, "black"))

        axes[2].set_ylabel('gCO2 (10³)', size=16)

        #global_min_co2 - (global_max_co2 * 0.003)
        axes[2].set_ylim(global_min_co2, global_max_co2+global_max_co2*0.03)
        if "brown" in output_folder_rel:
            axes[2].set_ylim(80_000, 105_000)  # 80 to 105 with 1e3 formatter
        else:
            axes[2].set_ylim(80_000, 90_000)  # 80 to 105 with 1e3 formatter


        sf = ScalarFormatter(useMathText=False)  # set True if you want ×10^3 style
        sf.set_scientific(True)
        sf.set_powerlimits((3, 3))  # force 10^3
        axes[2].yaxis.set_major_formatter(sf)
        axes[2].tick_params(axis='x', rotation=x_rotation, labelsize=tick_fs)
        axes[2].grid(axis='y', linestyle='--', alpha=0.7)
        axes[2].tick_params(axis='y', labelsize=tick_fs)

        plt.tight_layout()
        plt.margins(0, 0)
        output_path = os.path.join(output_folder_rel, f"plot_budget-{budget}_variant-{variant_mode}.png")
        plt.savefig(output_path, dpi=300)
        plt.show()

def plot_boxplots_costOld(
    input_file_name,
    output_folder_rel,
    shape,
    fig_scale=1.7,          # <--- scale everything
    axis_label_fs=20,       # x/y axis label fontsize
    tick_fs=18,             # tick labels fontsize
    title_fs=18             # if you add titles
):
    csv_file = os.path.join(os.path.dirname(__file__), input_file_name)
    os.makedirs(output_folder_rel, exist_ok=True)
    data = pd.read_csv(csv_file)

    global_max_utility = data[cp.UTILITY].max()
    global_max_cost = (data[cp.COST] / (data[cp.TOTAL_PROC_TIME] / 3600) / (data[cp.BUDGET] * 3) * 100).max()
    global_max_co2 = data[cp.CO2_EMISS_TOTAL].max()
    global_min_co2 = data[cp.CO2_EMISS_TOTAL].min()

    groups = data.groupby([cp.BUDGET, cp.VAR_MODE])

    for (budget, variant_mode), group_data in groups:
        plot_data = {}

        for policy in group_data[cp.POLICY].unique():
            if policy == "probabilistic-carbon-aware":
                grouped_by_policy = group_data[group_data[cp.POLICY] == policy].groupby([cp.ALPHA, cp.BETA])
                for (alpha, beta), sub_group in grouped_by_policy:
                    new_policy_name = f"{policy} ({alpha},{beta})"
                    plot_data[new_policy_name] = sub_group
            else:
                plot_data[policy] = group_data[group_data[cp.POLICY] == policy]

        utility_data, cost_budget_data, co2_data, labels = [], [], [], []

        if variant_mode != 0:
            add_QoS_no_var(data, budget, utility_data, cost_budget_data, co2_data, labels)

        for policy_name, sub_group in plot_data.items():
            grouped_by_seed = sub_group.groupby(cp.SEED)

            utility_values = grouped_by_seed[cp.UTILITY].mean().values
            co2_values = grouped_by_seed[cp.CO2_EMISS_TOTAL].mean().values
            cost_budget_percent = (
                (grouped_by_seed[cp.COST].mean() / (grouped_by_seed[cp.TOTAL_PROC_TIME].mean() / 3600))
                / (budget * 3)
            ) * 100

            policy_label = policy_labels_dict.get(policy_name, policy_name)
            labels.append(policy_label)

            utility_data.append(utility_values)
            cost_budget_data.append(cost_budget_percent.values)
            co2_data.append(co2_values)

        if variant_mode != 0:
            reorder_QoS_no_var(utility_data, cost_budget_data, co2_data, labels)

        # --- BIGGER FIGURE ---
        if shape == "h":
            base_w, base_h = 30, 12
            fig, axes = plt.subplots(1, 3, figsize=(base_w * fig_scale, base_h * fig_scale))
        else:
            base_w, base_h = 8, 8
            fig, axes = plt.subplots(3, 1, figsize=(base_w * fig_scale, base_h * fig_scale))

        x_rotation = 23

        common_box_kwargs = dict(
            patch_artist=True,
            showfliers=False,
        )


        # Utility boxplot
        bp_util = axes[0].boxplot(utility_data, labels=labels, **common_box_kwargs)
        for patch, label in zip(bp_util["boxes"], labels):
            patch.set_facecolor(policy_colors.get(label, "black"))
        axes[0].set_ylabel('Utility (10⁶)', fontsize=axis_label_fs)
        axes[0].set_ylim(0, global_max_utility + global_max_utility * 0.03)
        axes[0].tick_params(axis='x', rotation=x_rotation, labelsize=tick_fs)
        axes[0].tick_params(axis='y', labelsize=tick_fs)
        axes[0].grid(axis='y', linestyle='--', alpha=0.7)

        # Cost/Budget % boxplot
        bp_cost = axes[1].boxplot(cost_budget_data, labels=labels, **common_box_kwargs)
        for patch, label in zip(bp_cost["boxes"], labels):
            patch.set_facecolor(policy_colors.get(label, "black"))

        max_cost = 2 if budget > 5.0 else global_max_cost
        axes[1].set_ylabel('Cost/Budget (%)', fontsize=axis_label_fs)
        axes[1].set_ylim(0, max_cost)
        axes[1].tick_params(axis='x', rotation=x_rotation, labelsize=tick_fs)
        axes[1].tick_params(axis='y', labelsize=tick_fs)
        axes[1].grid(axis='y', linestyle='--', alpha=0.7)

        # CO2 Emissions boxplot
        bp_co2 = axes[2].boxplot(co2_data, labels=labels, **common_box_kwargs)
        for patch, label in zip(bp_co2["boxes"], labels):
            patch.set_facecolor(policy_colors.get(label, "black"))

        axes[2].set_ylabel('gCO2', fontsize=axis_label_fs)
        axes[2].set_ylim(global_min_co2, global_max_co2 + global_max_co2 * 0.03)

        sf = ScalarFormatter(useMathText=False)
        sf.set_scientific(True)
        sf.set_powerlimits((3, 3))
        axes[2].yaxis.set_major_formatter(sf)

        axes[2].tick_params(axis='x', rotation=x_rotation, labelsize=tick_fs)
        axes[2].tick_params(axis='y', labelsize=tick_fs)
        axes[2].grid(axis='y', linestyle='--', alpha=0.7)

        plt.tight_layout()
        plt.margins(0, 0)

        output_path = os.path.join(output_folder_rel, f"plot_budget-{budget}_variant-{variant_mode}.png")
        #plt.savefig(output_path, dpi=300)
        plt.show()


# Define policy renaming map
policy_labels_dict = {
    "probabilistic-carbon-aware (0.0,1.0)": "CO2",
    "probabilistic-carbon-aware (0.5,0.5)": "CO2&QoS",
    "probabilistic-carbon-aware (1.0,0.0)": "QoS",
    #"random-multi-region": "Rand",
    "random-multi-region-no-drop": "Rand",
    "basic-multi-region": "Base",
    "greedy-multi-region": "minR",
    "greedy-carbon-aware": "minCO2",
    "greedy-carbon-aware-strict": "minCO2Str",
    "energyless": "EnergyLess"
}

# Define colors for policies
policy_colors = {
    "CO2": "seagreen",
    "CO2&QoS": "olive",
    "QoS": "saddlebrown",
    "QoS-NV": "saddlebrown",
    "Rand": "red",
    "RandND": "black",
    "Base": "orange",
    "minR": "tan",
    "minCO2": "orchid",
    "minCO2Str": "royalblue",
    "EnergyLess": "lightblue"
}



def merge_2_csv_files(file1_path, file2_path, output_path):
    # Open the first CSV file
    with open(file1_path, 'r', newline='') as file1:
        reader1 = csv.reader(file1)
        header1 = next(reader1)  # Read header from the first file
        rows1 = list(reader1)    # Read the remaining rows of the first file

    # Open the second CSV file
    with open(file2_path, 'r', newline='') as file2:
        reader2 = csv.reader(file2)
        header2 = next(reader2)  # Read header from the second file
        rows2 = list(reader2)    # Read the remaining rows of the second file

    # Merge the rows (appending rows of the second file to the first file)
    merged_rows = rows1 + rows2

    # Write the merged data into the output CSV file
    with open(output_path, 'w', newline='') as output_file:
        writer = csv.writer(output_file)
        # Write the header of the first CSV file
        writer.writerow(header1)
        # Write all merged rows
        writer.writerows(merged_rows)

    print(f"CSV files merged successfully! Output saved to {output_path}")


def is_nan(value):
    return value != value  # Checks for NaN values

def process_csv_json_completionsDistributions(csv_path, json_folder, scenario):
    # Load the CSV file
    df = pd.read_csv(csv_path)

    # Ensure required columns exist
    for col in ["Completions", "Violations", "NetCompletions", "NormUtility", "NormEmissions","NormUtilityAll", "CompletionsDistribution"]:
        if col not in df.columns:
            df[col] = 0 if col != "CompletionsDistribution" else "{}"  # Initialize CompletionsDistribution as empty dict

    # Convert numeric columns to the correct type
    df["Budget"] = pd.to_numeric(df["Budget"], errors="coerce")
    df["Seed"] = pd.to_numeric(df["Seed"], errors="coerce")
    df["Variant_mode"] = pd.to_numeric(df["Variant_mode"], errors="coerce")
    df["OF-Alpha"] = pd.to_numeric(df.get("OF-Alpha", pd.Series(float("nan"), index=df.index)), errors="coerce")
    df["OF-Beta"] = pd.to_numeric(df.get("OF-Beta", pd.Series(float("nan"), index=df.index)), errors="coerce")

    # Regular expression pattern to extract values from the filename
    pattern = re.compile(
        r"Policy([^_]+)_.*?Budget([^_]+)_.*?Seed([^_]+)_.*?Variant_mode([^_.]+)"
        r"(?:_.*?OF-Alpha([^_]+)_.*?OF-Beta([\d]\.\d))?"
    )

    # Iterate over all JSON files in the folder
    for json_file in os.listdir(json_folder):

        if scenario == "brown" and "Green" in json_file:
            continue

        if scenario == "green" and "Brown" in json_file:
            continue

        if not json_file.endswith(".json"):
            continue  # Skip non-JSON files

        match = pattern.search(json_file)
        if not match:
            print(f"Skipping file (no match): {json_file}")
            continue

        # Extract values from the filename
        policy, budget, seed, variant_mode, alpha, beta = match.groups()
        budget, seed, variant_mode = float(budget), int(seed), int(variant_mode)
        alpha = float(alpha) if alpha is not None else float("nan")
        beta = float(beta) if beta is not None else float("nan")

        print(f"Processing: {json_file}")
        print(f"  Extracted: Policy={policy}, Budget={budget}, Seed={seed}, Variant_mode={variant_mode}, Alpha={alpha}, Beta={beta}")

        # Load the JSON file
        json_path = os.path.join(json_folder, json_file)
        with open(json_path, "r") as f:
            data = json.load(f)

        # Compute total completions and violations
        completions = sum(data.get("completions", {}).values())
        violations = sum(data.get("violations", {}).values())
        net_completions = completions - violations

        print(f"  JSON data: Completions={completions}, Violations={violations}, NetCompletions={net_completions}")

        # Compute "CompletionsDistribution" for each node, breaking down by class
        node_completions = {}

        for key, value in data.get("completions", {}).items():
            match = re.match(r"\(([^,]+),\s*([^,]+),\s*([^)]+)\)", key)  # Extract function, class, node
            if match:
                function_name, service_class, node = match.groups()

                if node not in node_completions:
                    if variant_mode == 1:
                        node_completions[node] = {
                            "total": {"all": 0, "standard": 0, "critical": 0},
                            "variants": {"all": 0, "standard": 0, "critical": 0},
                        }
                    else:
                        node_completions[node] = {
                            "total": {"all": 0, "standard": 0, "critical": 0}
                        }

                if "dispatcher" in node:
                    continue

                # Update totals
                node_completions[node]["total"]["all"] += value
                if service_class == "standard":
                    node_completions[node]["total"]["standard"] += value
                elif service_class == "critical":
                    node_completions[node]["total"]["critical"] += value

                # Update variants if function name contains "var"
                if "var" in function_name and variant_mode == 1:
                    node_completions[node]["variants"]["all"] += value
                    if service_class == "standard":
                        node_completions[node]["variants"]["standard"] += value
                    elif service_class == "critical":
                        node_completions[node]["variants"]["critical"] += value

        # Convert dictionary to JSON-like string format for CSV storage
        completions_distribution_str = json.dumps(node_completions)

        sum_co2_computation = 0
        for key, value in data.get("co2_emission_per_node", {}).items():
            sum_co2_computation += value

        # Find the corresponding row in the CSV
        if not is_nan(alpha) and not is_nan(beta):
            mask = (
                (df["Policy"] == policy) &
                (df["Budget"] == budget) &
                (df["Seed"] == seed) &
                (df["Variant_mode"] == variant_mode) &
                (df["OF-Alpha"].fillna(float("nan")) == alpha) &
                (df["OF-Beta"].fillna(float("nan")) == beta)
            )
        else:
            mask = (
                (df["Policy"] == policy) &
                (df["Budget"] == budget) &
                (df["Seed"] == seed) &
                (df["Variant_mode"] == variant_mode)
            )

        if mask.sum() == 0:
            print("  No matching row found in CSV!")
            continue  # Skip if no match found

        print(f"  Updating {mask.sum()} row(s) in CSV.")

        # Update values in the matching row(s)
        df.loc[mask, "Completions"] = completions
        df.loc[mask, "Violations"] = violations
        df.loc[mask, "NetCompletions"] = net_completions
        df.loc[mask, "CompletionsDistribution"] = completions_distribution_str  # Store the new column
        df.loc[mask, "CO2EmissComputation"] = sum_co2_computation  # Store the new column
        df.loc[mask, "CO2EmissTransmission"] = df.loc[mask,"CO2EmissTotal"].values[0] - float(sum_co2_computation)  # Store the new column

        # Prevent division by zero
        df.loc[mask, "NormUtility"] = df.loc[mask, "Utility"] / net_completions if net_completions > 0 else 0
        df.loc[mask, "NormEmissions"] = df.loc[mask, "CO2EmissTotal"] / net_completions if net_completions > 0 else 0

    # Save the updated CSV
    df.to_csv(csv_path, index=False)
    print(f"Updated CSV saved at {csv_path}")

def check_if_nan(value):
    return math.isnan(float(value))
# Example usage:
# process_csv_json("data.csv", "json_files_folder")


def plot_budget_dual_axis_variant_split(
    csv_path="/mnt/data/mainComparisonBrown.csv",
    policy_col="Policy",
    budget_col="Budget",
    type_scenario="Brown",
    alpha_col="OF-Alpha",
    beta_col="OF-Beta",
    variant_col="Variant_mode",
    emissions_col="NormEmissions",
    utility_col="NormUtility",
    alpha_value=0.5,
    beta_value=0.5,
    figsize=(12, 7),
):
    policy = ""
    if alpha_value == 0.5 and beta_value == 0.5:
        policy = "CO2&QoS-aware"
    elif alpha_value == 1.0 and beta_value == 0.0:
        policy = "QoS-aware"
    elif alpha_value == 0.0 and beta_value == 1.0:
        policy = "CO2-aware"
    title="Budget vs Normalized Emissions/Utility ("+policy+") - "+type_scenario

    # ---------------------------
    # 1) Read + validate
    # ---------------------------
    budgets_to_keep = (0.5, 5.0, 20.0, 50.0)
    df = pd.read_csv(csv_path)

    required = [
        policy_col, budget_col, alpha_col, beta_col,
        variant_col, emissions_col, utility_col
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}\nAvailable: {list(df.columns)}")

    # Numeric conversion
    for c in [budget_col, alpha_col, beta_col, variant_col, emissions_col, utility_col]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # ---------------------------
    # 2) Filter requested subset
    # ---------------------------
    d = df[
        (df[alpha_col] == alpha_value) &
        (df[beta_col] == beta_value) &
        (df[budget_col].isin(budgets_to_keep)) &
        (df[variant_col].isin([0, 1]))
    ].copy()

    d = d.dropna(subset=[policy_col, budget_col, variant_col, emissions_col, utility_col])

    if d.empty:
        raise ValueError(
            f"No rows found for alpha={alpha_value}, beta={beta_value}, "
            f"budgets={budgets_to_keep}, variant_mode in [0,1]."
        )

    # ---------------------------
    # 3) Aggregate over repeated rows/seeds
    # ---------------------------
    g = (
        d.groupby([policy_col, variant_col, budget_col], as_index=False)
         .agg({
             emissions_col: "mean",
             utility_col: "mean"
         })
         .sort_values([policy_col, variant_col, budget_col])
    )

    # ---------------------------
    # 4) Plot (dual axis)
    # ---------------------------
    fig, ax_left = plt.subplots(figsize=figsize)
    ax_right = ax_left.twinx()

    # Create many distinct colors (one color per line)
    # One "line" here = (policy, variant, metric-axis series).
    cmap = plt.cm.get_cmap("tab20", 100)

    color_idx = 0

    policies = sorted(g[policy_col].astype(str).unique())
    variant_marker = {0: "o", 1: "s"}

    for pol in policies:
        for vm in [0, 1]:
            s = g[(g[policy_col].astype(str) == pol) & (g[variant_col] == vm)].sort_values(budget_col)
            if s.empty:
                continue

            # left-axis line (NormEmissions) -> unique color
            c1 = cmap(color_idx); color_idx += 1
            ax_left.plot(
                s[budget_col].values,
                s[emissions_col].values,
                marker=variant_marker[vm],
                linestyle="-",
                linewidth=2,
                markersize=7,
                color="orange",
                label=f"{pol} | v={vm} | {emissions_col}"
            )

            # right-axis line (NormUtility) -> another unique color
            c2 = cmap(color_idx); color_idx += 1
            ax_right.plot(
                s[budget_col].values,
                s[utility_col].values,
                marker=variant_marker[vm],
                linestyle="--",
                linewidth=2,
                markersize=7,
                color="lightblue",
                label=f"{pol} | v={vm} | {utility_col}"
            )

    # Axes formatting
    ax_left.set_xlabel("Budget", fontsize=13)
    ax_left.set_ylabel(emissions_col, fontsize=13)
    ax_right.set_ylabel(utility_col, fontsize=13)
    ax_left.set_title(title, fontsize=14)

    # Only show ticks 0.5 and 5
    ax_left.set_xticks([0.5, 5.0])
    ax_left.set_xticklabels(["0.5", "5"])

    ax_left.grid(True, linestyle="--", alpha=0.35)

    # Merge legends
    h1, l1 = ax_left.get_legend_handles_labels()
    h2, l2 = ax_right.get_legend_handles_labels()
    ax_left.legend(h1 + h2, l1 + l2, loc="best", fontsize=9, ncol=1)

    plt.tight_layout()
    plt.show()


def createMainComparisonBrown():
    input_file_name1 = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown_1half.csv"
    input_file_name2 = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown_2half.csv"
    output_file = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown.csv"
    merge_2_csv_files(input_file_name1, input_file_name2, output_file)


    input_file_name1 = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown.csv"
    input_file_name2 = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown_normalized_1half.csv"
    output_file = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown.csv"
    merge_2_csv_files(input_file_name1, input_file_name2, output_file)

    input_file_name1 = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown.csv"
    input_file_name2 = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown_normalized_2half.csv"
    output_file = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown.csv"

    merge_2_csv_files(input_file_name1, input_file_name2, output_file)

def createMainComparisonGreen():
    input_file_name1 = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen_1half.csv"
    input_file_name2 = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen_2half.csv"
    output_file = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen.csv"
    merge_2_csv_files(input_file_name1, input_file_name2, output_file)


    input_file_name1 = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen.csv"
    input_file_name2 = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen_normalized_1half.csv"
    output_file = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen.csv"
    merge_2_csv_files(input_file_name1, input_file_name2, output_file)

    input_file_name1 = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen.csv"
    input_file_name2 = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen_normalized_2half.csv"
    output_file = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen.csv"

    merge_2_csv_files(input_file_name1, input_file_name2, output_file)

import matplotlib.dates as mdates

def plot_carbon_intensity_utc(pl_csv_path: str,
                              fr_csv_path: str,
                              start: str = '2023-01-01 00:00:00',
                              end:   str = '2023-01-03 23:00:00',
                              pl_color: str = 'tab:brown',
                              fr_color: str = 'tab:green'):

    # 1) Load data with UTC-aware parsing
    date_parser = lambda x: pd.to_datetime(x, utc=True)
    pl = pd.read_csv(pl_csv_path,
                     parse_dates=['Datetime (UTC)'],
                     date_parser=date_parser)
    fr = pd.read_csv(fr_csv_path,
                     parse_dates=['Datetime (UTC)'],
                     date_parser=date_parser)

    # 2) Define tz-aware window bounds
    start_ts = pd.to_datetime(start, utc=True)
    end_ts   = pd.to_datetime(end,   utc=True)

    # 3) Filter window
    pl_window = pl[(pl['Datetime (UTC)'] >= start_ts) & (pl['Datetime (UTC)'] <= end_ts)]
    fr_window = fr[(fr['Datetime (UTC)'] >= start_ts) & (fr['Datetime (UTC)'] <= end_ts)]

    # 4) Plot
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot(pl_window['Datetime (UTC)'],
            pl_window['Carbon Intensity gCO₂eq/kWh (direct)'],
            label='Poland', color=pl_color)
    ax.plot(fr_window['Datetime (UTC)'],
            fr_window['Carbon Intensity gCO₂eq/kWh (direct)'],
            label='France', color=fr_color)

    # 5) X-axis ticks every 6 hours
    locator = mdates.HourLocator(byhour=range(0, 24, 12), tz=mdates.UTC)
    formatter = mdates.DateFormatter('%H:%M\n%y-%m-%d', tz=mdates.UTC)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)
    ax.tick_params(axis='x', rotation=0, pad=15, labelsize=15)
    ax.tick_params(axis='y', labelsize=15)  # bigger y-tick labels

    ax.set_xlim(start_ts, end_ts)

    # 6) Labels, legend, layout
    ax.set_xlabel('Datetime', fontsize=18)  # <--- Bigger X label
    ax.set_ylabel('gCO₂eq/kWh', fontsize=18)  # <--- Bigger Y label
    ax.set_title('Carbon Intensity', fontsize=20)  # <--- Bigger Title
    ax.legend(fontsize=15)  # <--- Bigger Legend
    ax.legend()
    plt.tight_layout()
    plt.show()
    plt.sa

import pandas as pd
import numpy as np

def merge_csv_align_columns(csv_paths, output_path):
    dfs = []
    all_cols = set()

    # read all, collect union of columns
    for p in csv_paths:
        d = pd.read_csv(p)

        # make sure these exist everywhere (so plot_bar/groupby never fails)
        for c in ["OF-Alpha", "OF-Beta", "CompletionsDistribution"]:
            if c not in d.columns:
                d[c] = np.nan

        dfs.append(d)
        all_cols |= set(d.columns)

    # choose a nice stable column order (keeps your CSV readable)
    preferred = [
        "Policy","Budget","Seed","Variant_mode","OF-Alpha","OF-Beta",
        "Utility","Penalty","NetUtility","Cost","BudgetExcessPerc",
        "EnergyConsNode","EnergyConsTotal","TotalProcTime","CO2EmissTotal","ExtArrivals",
        "CompletionsDistribution","Completions","Violations","NetCompletions","NormUtility"
    ]
    cols = [c for c in preferred if c in all_cols] + [c for c in all_cols if c not in preferred]

    out = pd.concat([d.reindex(columns=cols) for d in dfs], ignore_index=True)
    out.to_csv(output_path, index=False)
    print(f"Saved {len(out)} rows -> {output_path}")


def plot_update_time_3_regions(
    csv_path,
    function_col="Functions",
    update_col="updateTime",
    regions_col="NumRegions",
    regions=(1, 3, 5),
    agg="mean",                 # "mean" | "median" | "min" | "max"
    figsize=(12, 6),
    # ---- font controls ----
    title_fs=24,
    label_fs=27,
    tick_fs=20,
    legend_fs=22,
    legend_title_fs=23
):
    df = pd.read_csv(csv_path)

    # Validate columns
    required = [function_col, update_col, regions_col]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}. Available: {list(df.columns)}")

    # Convert to numeric
    d = df[required].copy()
    d[function_col] = pd.to_numeric(d[function_col], errors="coerce")
    d[update_col] = pd.to_numeric(d[update_col], errors="coerce")
    d[regions_col] = pd.to_numeric(d[regions_col], errors="coerce")
    d = d.dropna()

    # Filter regions
    regions = [int(r) for r in regions]
    d = d[d[regions_col].isin(regions)]
    if d.empty:
        raise ValueError(f"No data found for {regions_col} in {regions}")

    # Aggregate duplicates for same (Functions, NumRegions)
    if agg not in {"mean", "median", "min", "max"}:
        raise ValueError("agg must be one of: 'mean', 'median', 'min', 'max'")
    g = d.groupby([function_col, regions_col], as_index=False)[update_col].agg(agg)

    # Marker style per region
    marker_map = {
        regions[0]: "o",
        regions[1]: "+",
        regions[2]: "D"
    }

    fig, ax = plt.subplots(figsize=figsize)

    for r in regions:
        s = g[g[regions_col] == r].sort_values(function_col)
        if s.empty:
            continue
        ax.plot(
            s[function_col].values,
            s[update_col].values,
            marker=marker_map.get(r, "o"),
            linewidth=1.8,
            markersize=7,
            label=f"{r} Cloud zones"
        )

    ax.set_xscale("log", base=2)

    ticks = [1, 2, 4, 8, 16, 32, 64, 128]
    all_x = sorted(g[function_col].unique())
    present_ticks = [t for t in ticks if t in all_x]
    ax.set_xticks(present_ticks)
    ax.set_xticklabels([str(t) for t in present_ticks], fontsize=tick_fs)

    ax.tick_params(axis='y', labelsize=tick_fs)

    ax.set_xlabel("Functions", fontsize=label_fs)
    ax.set_ylabel("Resolution Time (s)", fontsize=label_fs)

    #legend = ax.legend(title="Regions number", fontsize=legend_fs, title_fontsize=legend_title_fs)
    legend = ax.legend( fontsize=legend_fs)
    # optional: slightly bigger symbols in legend
    for h in legend.legendHandles:
        try:
            h.set_markersize(9)
            h.set_linewidth(2.0)
        except Exception:
            pass

    plt.tight_layout()
    plt.show()

import pandas as pd
import matplotlib.pyplot as plt

def plot_update_time_3_variants(
    csv_path="/mnt/data/scalability_tot.csv",
    function_col="Functions",
    update_col="updateTime",
    variants_col="NumVariants",
    variants=(2, 4, 6),
    agg="mean",                 # "mean" | "median" | "min" | "max"
    figsize=(12, 6),
    # ---- font controls ----
    title="System scalability",
    title_fs=24,
    label_fs=27,
    tick_fs=20,
    legend_fs=22,
    legend_title_fs=23
):
    df = pd.read_csv(csv_path)

    # Validate columns
    required = [function_col, update_col, variants_col]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}. Available: {list(df.columns)}")

    # Convert to numeric
    d = df[required].copy()
    d[function_col] = pd.to_numeric(d[function_col], errors="coerce")
    d[update_col] = pd.to_numeric(d[update_col], errors="coerce")
    d[variants_col] = pd.to_numeric(d[variants_col], errors="coerce")
    d = d.dropna()

    # Filter variants
    variants = [int(v) for v in variants]
    d = d[d[variants_col].isin(variants)]
    if d.empty:
        raise ValueError(f"No data found for {variants_col} in {variants}")

    # Aggregate duplicates for same (Functions, NumVariants)
    if agg not in {"mean", "median", "min", "max"}:
        raise ValueError("agg must be one of: 'mean', 'median', 'min', 'max'")
    g = d.groupby([function_col, variants_col], as_index=False)[update_col].agg(agg)

    # Marker style per variant
    marker_map = {
        variants[0]: "o",   # 2
        variants[1]: "+",   # 4
        variants[2]: "D"    # 6
    }

    fig, ax = plt.subplots(figsize=figsize)

    legend_label_map = {2: "1 Variant", 4: "3 Variants", 6: "5 Variants"}

    for v in variants:
        s = g[g[variants_col] == v].sort_values(function_col)
        if s.empty:
            continue
        ax.plot(
            s[function_col].values,
            s[update_col].values,
            marker=marker_map.get(v, "o"),
            linewidth=1.8,
            markersize=7,
            label=legend_label_map.get(v, f"{v} Variants")
        )

    # Log2 x-axis (like your previous plot)
    ax.set_xscale("log", base=2)

    # Show readable tick labels as 1,2,4,... (not 2^k)
    ticks = [1, 2, 4, 8, 16, 32, 64, 128]
    all_x = sorted(g[function_col].unique())
    present_ticks = [t for t in ticks if t in all_x]
    if present_ticks:
        ax.set_xticks(present_ticks)
        ax.set_xticklabels([str(int(t)) for t in present_ticks], fontsize=tick_fs)
    else:
        # fallback: use all available x values
        ax.set_xticks(all_x)
        ax.set_xticklabels([str(int(t)) if float(t).is_integer() else str(t) for t in all_x], fontsize=tick_fs)

    ax.tick_params(axis='y', labelsize=tick_fs)

    ax.set_xlabel("Functions", fontsize=label_fs)
    ax.set_ylabel("Resolution Time (s)", fontsize=label_fs)
    #ax.set_title(title, fontsize=title_fs)

    legend = ax.legend(
        #title="Variants number",
        fontsize=legend_fs,
        #title_fontsize=legend_title_fs
    )

    # optional: bigger legend markers/lines
    for h in legend.legendHandles:
        try:
            h.set_markersize(9)
            h.set_linewidth(2.0)
        except Exception:
            pass

    plt.tight_layout()
    plt.show()


def createAllPoliciesBrown():
    brown_csvs = [
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown_1half.csv",
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown_2half.csv",
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown_normalized_1half.csv",
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown_normalized_2half.csv",

        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_baseline/mainComparisonBrown_Baseline_1half.csv",
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_baseline/mainComparisonBrown_Baseline_2half.csv",
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_greedy/mainComparisonBrown_Greedy_1half.csv",
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_greedy/mainComparisonBrown_Greedy_2half.csv",

        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_energyless/energylessBrown_1half.csv",
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_energyless/energylessBrown_2half.csv",

    ]

    out_csv = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown_allPolicies.csv"
    merge_csv_align_columns(brown_csvs, out_csv)
    


def createAllPoliciesGreen():
    green_csvs = [
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen_1half.csv",
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen_2half.csv",
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen_normalized_1half.csv",
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen_normalized_2half.csv",

        # add your greedy / baseline csvs here too
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_baseline/mainComparisonGreen_Baseline_1half.csv",
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_baseline/mainComparisonGreen_Baseline_2half.csv",
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_greedy/mainComparisonGreen_Greedy_1half.csv",
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_greedy/mainComparisonGreen_Greedy_2half.csv",

        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_energyless/energylessGreen_1half.csv",
        "/home/cecilia/workspace/faas-offloading/030226_10fun_results_energyless/energylessGreen_2half.csv",

    ]

    out_csv = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen_allPolicies.csv"
    merge_csv_align_columns(green_csvs, out_csv)


if __name__ == "__main__":
    brown = "brown_plots_030226_10fun"
    green = "green_plots_030226_10fun"
    brown_norm = "brown_norm_plots"


    csv_path ="/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown.csv"
    plot_budget_dual_axis_variant_split(csv_path=csv_path)

    csv_path ="/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen.csv"
    plot_budget_dual_axis_variant_split(csv_path=csv_path, type_scenario="Green")
    '''


    input_file_name = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown_allPolicies.csv"
    #plot_boxplots_cost(input_file_name, brown, "v")

    input_file_name = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen_allPolicies.csv"
    #plot_boxplots_cost(input_file_name, green, "v")




    #plot_update_time_3_variants("/home/cecilia/workspace/fromLinuxNero/100226_results_scalability_3/scalability_tot.csv")
    #plot_update_time_3_regions("/home/cecilia/workspace/fromLinuxNero/040226_results_scalability/scalability_total.csv")
    # =====================

    
    createAllPoliciesBrown()

    csv_path ="/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown_allPolicies.csv"
    json_folder = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/"
    #if not os.path.exists(csv_path):
    process_csv_json_completionsDistributions(csv_path, json_folder, "brown")

    input_file_name = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown_allPolicies.csv"
    plot_boxplots_cost(input_file_name, brown, "v")

    # =====================
    createMainComparisonBrown()


    csv_path ="/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown.csv"
    json_folder = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/"

    #if not os.path.exists(csv_path):
    process_csv_json_completionsDistributions(csv_path, json_folder, "brown")


    input_file_name = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonBrown.csv"
    plot_bar(input_file_name, brown)

    # =====================
    createAllPoliciesGreen()

    csv_path ="/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen_allPolicies.csv"
    json_folder = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/"
    #if not os.path.exists(csv_path):
    process_csv_json_completionsDistributions(csv_path, json_folder, "green")


    input_file_name = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen_allPolicies.csv"
    plot_boxplots_cost(input_file_name, green, "v")

    createMainComparisonGreen()

    csv_path = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen.csv"
    json_folder = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/"
    #if not os.path.exists(csv_path):
    process_csv_json_completionsDistributions(csv_path, json_folder, "green")

    input_file_name = "/home/cecilia/workspace/faas-offloading/030226_10fun_results_probabilistic/mainComparisonGreen.csv"
    plot_bar(input_file_name, green)
    '''


    '''
    #plot_carbon_intensity_utc(
    #pl_csv_path='/home/cecilia/workspace/faas-offloading/co2_traces/PL_2023_hourly.csv',
    #fr_csv_path='/home/cecilia/workspace/faas-offloading/co2_traces/FR_2023_hourly.csv',
    #pl_color='brown',
    #fr_color='green'
    #)
    
    '''











