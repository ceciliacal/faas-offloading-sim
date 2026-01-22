import csv
import math
import re
import os
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import conf_plots as cp
from matplotlib.patches import Patch

node_colors_brown_scenario = {
    "cloud_node_a": "saddlebrown",
    "cloud_node_b": "seagreen",
    "edge_node_a": "burlywood",
    "edge_node_b": "navajowhite",
    "edge_node_c": "linen"
}

node_colors_green_scenario = {
    "cloud_node_a": "seagreen",
    "cloud_node_b": "saddlebrown",
    "edge_node_a": "darkseagreen",
    "edge_node_b": "palegoldenrod",
    "edge_node_c": "lightgreen"
}



def plot_bar(input_file_name, output_folder_rel):
    csv_file = os.path.join(os.path.dirname(__file__), input_file_name)
    os.makedirs(output_folder_rel, exist_ok=True)
    data = pd.read_csv(csv_file)

    required_columns = [
        cp.BUDGET, cp.VAR_MODE, cp.ALPHA, cp.BETA, cp.POLICY,
        cp.UTILITY, cp.CO2_EMISS_TOTAL, cp.SEED, cp.COMPLETIONS_DISTRIBUTION
    ]
    groups = data.groupby([cp.BUDGET, cp.VAR_MODE])

    if "brown" in output_folder_rel:
        node_colors = node_colors_brown_scenario
    else:
        node_colors = node_colors_green_scenario

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
        fig, ax = plt.subplots(figsize=(12, 6))
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
                except (json.JSONDecodeError, KeyError):
                    continue  # Skip invalid JSON entries

                completion_values = {key: {"(f,s)": 0, "(f,c)": 0, "(v,s)": 0, "(v,c)": 0}
                                     for key in node_colors.keys()}

                for node, node_data in completion_json.items():
                    if node in node_colors:
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
                "(f,s)": {node: sum(c[node]["(f,s)"] for c in completions) for node in node_colors},
                "(f,c)": {node: sum(c[node]["(f,c)"] for c in completions) for node in node_colors},
                "(v,s)": {node: sum(c[node]["(v,s)"] for c in completions) for node in node_colors},
                "(v,c)": {node: sum(c[node]["(v,c)"] for c in completions) for node in node_colors}
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
            edge_nodes = ["edge_node_a", "edge_node_b", "edge_node_c"]

            # 2) Sum up f,s and f,c for each group
            fs_cloud_a = aggregated_values["(f,s)"]["cloud_node_a"]
            fs_cloud_b = aggregated_values["(f,s)"]["cloud_node_b"]
            fs_edge = sum(aggregated_values["(f,s)"][n] for n in edge_nodes)

            fc_cloud_a = aggregated_values["(f,c)"]["cloud_node_a"]
            fc_cloud_b = aggregated_values["(f,c)"]["cloud_node_b"]
            fc_edge = sum(aggregated_values["(f,c)"][n] for n in edge_nodes)

            # 3) Sum up v,s and v,c for edges only (cloud variants assumed zero)
            if variant_mode == 1:
                vs_edge = sum(aggregated_values["(v,s)"][n] for n in edge_nodes)
                vc_edge = sum(aggregated_values["(v,c)"][n] for n in edge_nodes)
            else:
                vs_edge = vc_edge = 0

            # pick one of the edge colors to use for the whole zone
            edge_color = node_colors[edge_nodes[0]]
            variant_color = node_colors[edge_nodes[1]]

            # — plot the STANDARD bar (bar_positions[0]) —
            bottom = 0
            # Cloud A
            ax.bar(bar_positions[0],
                   fs_cloud_a,
                   width,
                   color=node_colors["cloud_node_a"],
                   edgecolor="black")
            bottom += fs_cloud_a

            # Cloud B
            ax.bar(bar_positions[0],
                   fs_cloud_b,
                   width,
                   color=node_colors["cloud_node_b"],
                   edgecolor="black",
                   bottom=bottom)
            bottom += fs_cloud_b

            # Edge Zone (no variants)
            ax.bar(bar_positions[0],
                   fs_edge,
                   width,
                   color=edge_color,
                   edgecolor="black",
                   bottom=bottom)
            bottom += fs_edge

            # Function Variant (hatched)
            if variant_mode == 1:
                ax.bar(bar_positions[0],
                       vs_edge,
                       width,
                       color=variant_color,
                       edgecolor="black",
                       hatch="x",
                       bottom=bottom)

            # — plot the CRITICAL bar (bar_positions[1]) —
            bottom = 0
            ax.bar(bar_positions[1],
                   fc_cloud_a,
                   width,
                   color=node_colors["cloud_node_a"],
                   edgecolor="black")
            bottom += fc_cloud_a

            ax.bar(bar_positions[1],
                   fc_cloud_b,
                   width,
                   color=node_colors["cloud_node_b"],
                   edgecolor="black",
                   bottom=bottom)
            bottom += fc_cloud_b

            ax.bar(bar_positions[1],
                   fc_edge,
                   width,
                   color=edge_color,
                   edgecolor="black",
                   bottom=bottom)
            bottom += fc_edge

            if variant_mode == 1:
                ax.bar(bar_positions[1],
                       vc_edge,
                       width,
                       color=variant_color,
                       edgecolor="black",
                       hatch="x",
                       bottom=bottom)

            # — rebuild a 4-entry legend —
            legend_handles = [
                Patch(facecolor=node_colors["cloud_node_a"], edgecolor="black", label="Cloud region A"),
                Patch(facecolor=node_colors["cloud_node_b"], edgecolor="black", label="Cloud region B"),
                Patch(facecolor=edge_color, edgecolor="black", label="Edge Zone - no Variant execution"),
            ]
            if variant_mode == 1:
                legend_handles.append(
                    Patch(facecolor=variant_color, edgecolor="black", hatch="x", label="Edge Zone - Variant execution")
                )

            ax.legend(
                handles=legend_handles,
                loc="upper right",  # position legend at upper right inside the axes
                bbox_to_anchor=(0.98, 0.98),  # slight inset from the very corner
                frameon=True,
                edgecolor="black",
                title="Legend",
                fontsize=11  # optional: shrink text if needed
            )

            # ————————————————————————————————————————

        # Set x-axis labels (First level: Closest to bars)
        ax.set_xticks(x_positions)
        ax.set_xticklabels(x_labels_completion, rotation=0, ha="center", fontsize=12)

        # Add second-level x labels (Policies BELOW the first labels)
        for pos, policy in zip(policy_tick_positions, policy_labels_list):
            ax.text(pos,
                    -0.08,  # 8% below the x-axis
                    policy,
                    ha='center',
                    va='top',
                    fontsize=13,
                    transform=ax.get_xaxis_transform())  # interpret y in axis coords

        ax.set_ylabel("Number of Completed Requests", fontsize=13)

        plt.subplots_adjust(right=0.8, bottom=0.2)  # Extend space (increase if needed)

        output_path = os.path.join(output_folder_rel, f"completion_{budget}_{variant_mode}.png")
        plt.tight_layout()
        plt.savefig(output_path)
        plt.show()
        plt.close()


def format_yticks(axis):
    """Formats the y-axis labels to always show '.0' for whole numbers."""
    yticks = axis.get_yticks()
    axis.set_yticks(yticks)  # Ensure ticks are set
    axis.set_yticklabels([f"{tick:.1f}" if tick % 1 else f"{int(tick)}.0" for tick in yticks])


def format_ticks(x, _):
    return f"{x:.1f}"  # Forces float format (e.g., 3.0 instead of 3)

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
    labels.append("FGCS")

def reorder_QoS_no_var(utility_data, cost_budget_data, co2_data, labels):
    # find where QoS-no-var and QoS live
    i0 = labels.index("FGCS")
    iq = labels.index("QoS")

    # pull QoS-no-var out of each list
    u0 = utility_data.pop(i0)
    c0 = cost_budget_data.pop(i0)
    co20 = co2_data.pop(i0)
    labels.pop(i0)

    # if QoS-no-var was before QoS, popping it shifts QoS's index down by 1
    if i0 < iq:
        iq -= 1

    # insert QoS-no-var immediately after QoS
    insert_at = 0
    utility_data.insert(insert_at, u0)
    cost_budget_data.insert(insert_at, c0)
    co2_data.insert(insert_at, co20)
    labels.insert(insert_at, "FGCS")


def plot_boxplots_cost(input_file_name, output_folder_rel, shape):
    csv_file = os.path.join(os.path.dirname(__file__), input_file_name)
    os.makedirs(output_folder_rel, exist_ok=True)
    data = pd.read_csv(csv_file)

    # Convert CO₂ emissions to 10^3
    data[cp.CO2_EMISS_TOTAL] /= 1000

    # Compute global max values for each type across all scenarios
    global_max_utility = data[cp.UTILITY].max()
    global_max_cost = (data[cp.COST] / (data[cp.TOTAL_PROC_TIME] / 3600) / (data[cp.BUDGET] * 3) * 100).max()
    global_max_co2 = data[cp.CO2_EMISS_TOTAL].max()

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
            fig, axes = plt.subplots(3, 1, figsize=(6, 6))

        # Utility boxplot
        bp_util = axes[0].boxplot(utility_data, labels=labels, patch_artist=True, showfliers=False)
        for patch, label in zip(bp_util["boxes"], labels):
            patch.set_facecolor(policy_colors.get(label, "black"))
        axes[0].set_ylabel('Utility (10⁶)', size=12)
        axes[0].set_ylim(0, global_max_utility) #+ (global_max_utility * 0.03))
        axes[0].tick_params(axis='x', rotation=15)
        axes[0].grid(axis='y', linestyle='--', alpha=0.7)

        # Cost/Budget % boxplot
        if budget > 0.5:
            global_max_cost = 4.0
            y_lim = global_max_cost #+ (global_max_cost * 0.005)
        else:
            y_lim = global_max_cost #+ (global_max_cost * 0.08)
        bp_cost = axes[1].boxplot(cost_budget_data, labels=labels, patch_artist=True, showfliers=False)
        for patch, label in zip(bp_cost["boxes"], labels):
            patch.set_facecolor(policy_colors.get(label, "black"))

        axes[1].set_ylabel('Cost/Budget (%)', size=12)
        axes[1].set_ylim(0, y_lim)
        axes[1].tick_params(axis='x', rotation=15)
        axes[1].grid(axis='y', linestyle='--', alpha=0.7)
        #axes[1].yaxis.set_major_formatter(FuncFormatter(format_ticks))

        # CO2 Emissions boxplot
        bp_co2 = axes[2].boxplot(co2_data, labels=labels, patch_artist=True, showfliers=False)
        for patch, label in zip(bp_co2["boxes"], labels):
            patch.set_facecolor(policy_colors.get(label, "black"))

        axes[2].set_ylabel('gCO2 (10³)', size=12)
        axes[2].set_ylim(0, global_max_co2)#+ (global_max_co2 * 0.03))
        axes[2].tick_params(axis='x', rotation=15)
        axes[2].grid(axis='y', linestyle='--', alpha=0.7)

        plt.tight_layout()
        plt.margins(0, 0)
        output_path = os.path.join(output_folder_rel, f"plot_budget-{budget}_variant-{variant_mode}.png")
        plt.savefig(output_path, dpi=300)
        plt.show()

# Define policy renaming map
policy_labels_dict = {
    "probabilistic-carbon-aware (0.0,1.0)": "CO2",
    "probabilistic-carbon-aware (0.5,0.5)": "CO2&QoS",
    "probabilistic-carbon-aware (1.0,0.0)": "QoS",
    "random-multi-region": "Rand",
    "random-multi-region-no-drop": "Rand-no-drop",
    "basic-multi-region": "Base",
    "greedy-multi-region": "minR",
    "greedy-carbon-aware": "minCO2",
    "greedy-carbon-aware-strict": "minCO2Str"
}

# Define colors for policies
policy_colors = {
    "CO2": "seagreen",
    "CO2&QoS": "olive",
    "QoS": "saddlebrown",
    "FGCS": "saddlebrown",
    "Rand": "red",
    "Base": "orange",
    "minR": "tan",
    "minCO2": "orchid",
    "minCO2Str": "royalblue"
}

def mean_std(input_file_name):
    #csv_file = os.path.join(os.path.dirname(__file__), input_file_name)
    df = pd.read_csv(input_file_name)

    # Assume df is your DataFrame with columns 'utility' and 'CO2EmissTotal'
    mean_utility = df['Utility'].mean()
    std_utility = df['Utility'].std(ddof=1)

    mean_energy = df['CO2EmissTotal'].mean()
    std_energy = df['CO2EmissTotal'].std(ddof=1)

    print("Utility: Mean =", mean_utility, "Std Dev =", std_utility)
    print("Energy: Mean =", mean_energy, "Std Dev =", std_energy)




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


def merge_csv_files(*input_files, output_path):
    # Initialize an empty list for merged rows and header
    merged_rows = []
    header = None

    # Iterate through all input files
    for index, file_path in enumerate(input_files):
        with open(file_path, 'r', newline='') as file:
            reader = csv.reader(file)
            file_header = next(reader)  # Read header

            # Set the header for the first file, and make sure subsequent files' headers are ignored
            if index == 0:
                header = file_header  # Set header from the first file
            else:
                next(reader)  # Skip the header of the current file

            # Add rows from the current file to merged_rows
            merged_rows.extend(list(reader))

    # Write the merged data into the output CSV file
    with open(output_path, 'w', newline='') as output_file:
        writer = csv.writer(output_file)
        # Write the header (from the first file)
        writer.writerow(header)
        # Write all merged rows
        writer.writerows(merged_rows)

    print(f"CSV files merged successfully! Output saved to {output_path}")



def is_nan(value):
    return value != value  # Checks for NaN values

def process_csv_json_completionsDistributions(csv_path, json_folder, scenario):
    # Load the CSV file
    df = pd.read_csv(csv_path)

    # Ensure required columns exist
    for col in ["Completions", "Violations", "NetCompletions", "NormUtility", "CompletionsDistribution"]:
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

    # Save the updated CSV
    df.to_csv(csv_path, index=False)
    print(f"Updated CSV saved at {csv_path}")

def check_if_nan(value):
    return math.isnan(float(value))
# Example usage:
# process_csv_json("data.csv", "json_files_folder")

def createMainComparisonBrown():
    input_file_name1 = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown_1half.csv"
    input_file_name2 = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown_2half.csv"
    output_file = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown.csv"
    merge_2_csv_files(input_file_name1, input_file_name2, output_file)


    input_file_name1 = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown.csv"
    input_file_name2 = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown_normalized_1half.csv"
    output_file = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown.csv"
    merge_2_csv_files(input_file_name1, input_file_name2, output_file)

    input_file_name1 = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown.csv"
    input_file_name2 = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown_normalized_2half.csv"
    output_file = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown.csv"

    merge_2_csv_files(input_file_name1, input_file_name2, output_file)

def createMainComparisonGreen():
    input_file_name1 = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen_1half.csv"
    input_file_name2 = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen_2half.csv"
    output_file = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen.csv"
    merge_2_csv_files(input_file_name1, input_file_name2, output_file)


    input_file_name1 = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen.csv"
    input_file_name2 = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen_normalized_1half.csv"
    output_file = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen.csv"
    merge_2_csv_files(input_file_name1, input_file_name2, output_file)

    input_file_name1 = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen.csv"
    input_file_name2 = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen_normalized_2half.csv"
    output_file = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen.csv"

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


def createAllPoliciesBrown():
    brown_csvs = [
        "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown_1half.csv",
        "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown_2half.csv",
        "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown_normalized_1half.csv",
        "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown_normalized_2half.csv",

        # add your greedy / baseline csvs here too
        "/home/cecilia/workspace/faas-offloading/190126_results_baseline/mainComparisonBrown_Baseline_1half.csv",
        "/home/cecilia/workspace/faas-offloading/190126_results_baseline/mainComparisonBrown_Baseline_2half.csv",
        "/home/cecilia/workspace/faas-offloading/190126_results_greedy/mainComparisonBrown_Greedy_1half.csv",
        "/home/cecilia/workspace/faas-offloading/190126_results_greedy/mainComparisonBrown_Greedy_2half.csv",

    ]

    out_csv = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown_allPolicies.csv"
    merge_csv_align_columns(brown_csvs, out_csv)
    


def createAllPoliciesGreen():
    green_csvs = [
        "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen_1half.csv",
        "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen_2half.csv",
        "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen_normalized_1half.csv",
        "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen_normalized_2half.csv",

        # add your greedy / baseline csvs here too
        "/home/cecilia/workspace/faas-offloading/190126_results_baseline/mainComparisonGreen_Baseline_1half.csv",
        "/home/cecilia/workspace/faas-offloading/190126_results_baseline/mainComparisonGreen_Baseline_2half.csv",
        "/home/cecilia/workspace/faas-offloading/190126_results_greedy/mainComparisonGreen_Greedy_1half.csv",
        "/home/cecilia/workspace/faas-offloading/190126_results_greedy/mainComparisonGreen_Greedy_2half.csv",

    ]

    out_csv = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen_allPolicies.csv"
    merge_csv_align_columns(green_csvs, out_csv)


# Usage example
if __name__ == "__main__":
    brown = "brown_plots_190126"
    green = "green_plots_190126"
    brown_norm = "brown_norm_plots"

    # =====================
    createAllPoliciesBrown()

    csv_path ="/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown_allPolicies.csv"
    json_folder = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/"
    process_csv_json_completionsDistributions(csv_path, json_folder, "brown")

    input_file_name = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown_allPolicies.csv"
    plot_boxplots_cost(input_file_name, brown, "v")

    # =====================
    createMainComparisonBrown()

    csv_path ="/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown.csv"
    json_folder = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/"
    process_csv_json_completionsDistributions(csv_path, json_folder, "brown")

    input_file_name = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonBrown.csv"
    plot_bar(input_file_name, brown)
    # =====================

    createMainComparisonGreen()
    csv_path ="/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen.csv"
    json_folder = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/"
    process_csv_json_completionsDistributions(csv_path, json_folder, "green")

    createAllPoliciesGreen()

    input_file_name = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen_allPolicies.csv"
    plot_boxplots_cost(input_file_name, green, "v")

    input_file_name = "/home/cecilia/workspace/faas-offloading/190126_results_probabilistic/mainComparisonGreen.csv"
    plot_bar(input_file_name, green)

    '''
    plot_carbon_intensity_utc(
    pl_csv_path='/home/cecilia/workspace/faas-offloading/co2_traces/PL_2023_hourly.csv',
    fr_csv_path='/home/cecilia/workspace/faas-offloading/co2_traces/FR_2023_hourly.csv',
    pl_color='brown',
    fr_color='green'
    ) 
    '''











