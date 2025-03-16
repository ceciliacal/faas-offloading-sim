

import conf_plots as cp
import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

def plot_boxplots(input_file_name, output_folder="140325_results_probabilistic/plots"):
    csv_file = os.path.join(os.path.dirname(__file__), input_file_name)
    os.makedirs(output_folder, exist_ok=True)
    data = pd.read_csv(csv_file)

    required_columns = [cp.BUDGET, cp.VAR_MODE, cp.ALPHA, cp.BETA, cp.POLICY, cp.UTILITY, cp.CO2_EMISS_TOTAL, cp.SEED]
    groups = data.groupby([cp.BUDGET, cp.VAR_MODE])

    for (budget, variant_mode), group_data in groups:
        plot_data = {}

        for policy in group_data[cp.POLICY].unique():
            if policy == "probabilistic-carbon-aware":
                grouped_by_policy = group_data[group_data[cp.POLICY] == policy].groupby([cp.ALPHA, cp.BETA])
                for (alpha, beta), sub_group in grouped_by_policy:
                    new_policy_name = f"{policy} ({alpha}, {beta})"
                    plot_data[new_policy_name] = sub_group
            else:
                plot_data[policy] = group_data[group_data[cp.POLICY] == policy]

        utility_data = []
        co2_data = []
        labels = []

        for policy_name, sub_group in plot_data.items():
            grouped_by_seed = sub_group.groupby(cp.SEED)
            utility_values = grouped_by_seed[cp.UTILITY].mean().values
            co2_values = grouped_by_seed[cp.CO2_EMISS_TOTAL].mean().values

            utility_data.append(utility_values)
            co2_data.append(co2_values)
            labels.append(policy_name)

        # Create figure and subplots
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))

        # Plot Utility
        axes[0].boxplot(utility_data, labels=labels, showfliers=False)
        axes[0].set_title(f'Utility (Budget={budget}, Variant={variant_mode})')
        axes[0].set_xlabel('Policy')
        axes[0].set_ylabel('Utility')
        axes[0].tick_params(axis='x', rotation=45)
        axes[0].grid(axis='y', linestyle='--', alpha=0.7)

        # Plot CO2 Emissions
        bp = axes[1].boxplot(co2_data, labels=labels, showfliers=False)
        axes[1].set_title(f'CO2 Emissions (Budget={budget}, Variant={variant_mode})')
        axes[1].set_xlabel('Policy')
        axes[1].set_ylabel('CO2 Emissions')
        axes[1].tick_params(axis='x', rotation=45)
        axes[1].grid(axis='y', linestyle='--', alpha=0.7)  # Horizontal lines for better readability

        # Strictly get the max whisker value per plot
        max_whiskers = [max(whisker.get_ydata()) for whisker in bp["whiskers"]] if bp["whiskers"] else [0]
        max_y = max(max_whiskers) if max_whiskers else 0

        # Set CO2 y-axis limit dynamically
        upper_limit = max_y + (0.1 * max_y)  # Extend limit slightly
        axes[1].set_ylim(0, upper_limit)

        # Add more tick values on the y-axis
        yticks = np.linspace(0, upper_limit, num=10)  # More values for better precision
        axes[1].set_yticks(yticks)

        # Adjust layout and save plot
        plt.tight_layout()
        exp_scenario = input_file_name.split(".")[0]
        filename = f"{exp_scenario}_budget-{budget}_variant-{variant_mode}.png"
        save_path = os.path.join(output_folder, filename)
        plt.savefig(save_path, dpi=300)
        plt.show()


def plot_boxplots_cost(input_file_name, output_folder="plots_cost"):
    csv_file = os.path.join(os.path.dirname(__file__), input_file_name)
    os.makedirs(output_folder, exist_ok=True)
    data = pd.read_csv(csv_file)

    # Ensure relevant columns exist
    required_columns = [
        cp.BUDGET, cp.VAR_MODE, cp.COST, cp.ALPHA, cp.BETA, cp.POLICY, cp.UTILITY, cp.CO2_EMISS_TOTAL, cp.SEED, cp.TOTAL_PROC_TIME
    ]

    # Group by budget and variant mode
    groups = data.groupby([cp.BUDGET, cp.VAR_MODE])

    for (budget, variant_mode), group_data in groups:
        # Create a dictionary to store data for plotting
        plot_data = {}

        for policy in group_data[cp.POLICY].unique():
            if policy == "probabilistic-carbon-aware":
                grouped_by_policy = group_data[group_data[cp.POLICY] == policy].groupby([cp.ALPHA, cp.BETA])
                for (alpha, beta), sub_group in grouped_by_policy:
                    new_policy_name = f"{policy} ({alpha}, {beta})"
                    plot_data[new_policy_name] = sub_group
            else:
                plot_data[policy] = group_data[group_data[cp.POLICY] == policy]

        # Prepare data for Utility, Cost/Budget %, and CO2 Emissions boxplots
        utility_data = []
        cost_budget_data = []
        co2_data = []
        labels = []

        for policy_name, sub_group in plot_data.items():
            grouped_by_seed = sub_group.groupby(cp.SEED)

            utility_values = grouped_by_seed[cp.UTILITY].mean().values
            co2_values = grouped_by_seed[cp.CO2_EMISS_TOTAL].mean().values

            cost_budget_percent = (
                (grouped_by_seed[cp.COST].mean() / (grouped_by_seed[cp.TOTAL_PROC_TIME].mean() / 3600))
                / (budget * 3)
            ) * 100  # Compute Cost/Budget %

            utility_data.append(utility_values)
            cost_budget_data.append(cost_budget_percent.values)
            co2_data.append(co2_values)
            labels.append(policy_name)

        # Create three separate plots
        fig, axes = plt.subplots(1, 3, figsize=(18, 6))

        # Utility boxplot
        axes[0].boxplot(utility_data, labels=labels, showfliers=False)
        axes[0].set_title(f'Utility (Budget={budget}, Variant={variant_mode})')
        axes[0].set_xlabel('Policy')
        axes[0].set_ylabel('Utility')
        axes[0].tick_params(axis='x', rotation=90)
        axes[0].set_ylim(bottom=0)
        axes[0].grid(axis='y', linestyle='--', alpha=0.7)

        # Cost/Budget % boxplot
        axes[1].boxplot(cost_budget_data, labels=labels, showfliers=False)
        axes[1].set_title(f'Cost/Budget % (Budget={budget}, Variant={variant_mode})')
        axes[1].set_xlabel('Policy')
        axes[1].set_ylabel('Cost/Budget (%)')
        axes[1].tick_params(axis='x', rotation=90)
        axes[1].set_ylim(bottom=0)
        axes[1].grid(axis='y', linestyle='--', alpha=0.7)

        # CO2 Emissions boxplot
        bp = axes[2].boxplot(co2_data, labels=labels, showfliers=False)
        axes[2].set_title(f'CO2 Emissions (Budget={budget}, Variant={variant_mode})')
        axes[2].set_xlabel('Policy')
        axes[2].set_ylabel('CO2 Emissions')
        axes[2].tick_params(axis='x', rotation=90)
        axes[2].grid(axis='y', linestyle='--', alpha=0.7)

        # Strictly get the max whisker value per plot
        max_whiskers = [max(whisker.get_ydata()) for whisker in bp["whiskers"]] if bp["whiskers"] else [0]
        max_y = max(max_whiskers) if max_whiskers else 0

        # Set CO2 y-axis limit dynamically
        upper_limit = max_y + (0.1 * max_y)  # Extend limit slightly
        axes[2].set_ylim(0, upper_limit)

        # Add more tick values on the CO2 y-axis
        yticks = np.linspace(0, upper_limit, num=10)  # More values for better precision
        axes[2].set_yticks(yticks)

        # Adjust layout and save plot
        plt.tight_layout()
        exp_scenario = input_file_name.split(".")[0]
        filename = f"{exp_scenario}_budget-{budget}_variant-{variant_mode}.png"
        save_path = os.path.join(output_folder, filename)
        plt.savefig(save_path, dpi=300)
        plt.show()

def plot_boxplots_cost_probabilistic_only(input_file_name, output_folder="plots_cost_probabilistic_only"):
    csv_file = os.path.join(os.path.dirname(__file__), input_file_name)
    os.makedirs(output_folder, exist_ok=True)
    data = pd.read_csv(csv_file)

    # Ensure relevant columns exist
    required_columns = [cp.BUDGET, cp.VAR_MODE, cp.COST, cp.ALPHA, cp.BETA, cp.POLICY, cp.UTILITY, cp.CO2_EMISS_TOTAL,
                        cp.SEED]

    # Filter policies containing "probabilistic"
    data = data[data[cp.POLICY].str.contains("probabilistic", case=False, na=False)]

    # Group by budget and variant mode
    groups = data.groupby([cp.BUDGET, cp.VAR_MODE])

    for (budget, variant_mode), group_data in groups:
        # Create a dictionary to store data for plotting
        plot_data = {}

        for policy in group_data[cp.POLICY].unique():
            if policy == "probabilistic-carbon-aware":
                # For "probabilistic-carbon-aware," group by (alpha, beta) pairs
                grouped_by_policy = group_data[group_data[cp.POLICY] == policy].groupby([cp.ALPHA, cp.BETA])
                for (alpha, beta), sub_group in grouped_by_policy:
                    new_policy_name = f"{policy} ({alpha}, {beta})"
                    plot_data[new_policy_name] = sub_group
            else:
                # For other policies, group directly
                plot_data[policy] = group_data[group_data[cp.POLICY] == policy]

        # Prepare data for utility and Cost/Budget % boxplots
        utility_data = []
        cost_data = []
        labels = []

        for policy_name, sub_group in plot_data.items():
            # Group by seed and collect utility and Cost/Budget % data
            grouped_by_seed = sub_group.groupby(cp.SEED)
            utility_values = grouped_by_seed[cp.UTILITY].mean().values
            cost_values = (grouped_by_seed[cp.COST].mean() / budget * 100).values  # Calculate Cost/Budget %

            utility_data.append(utility_values)
            cost_data.append(cost_values)
            labels.append(policy_name)

        # Create two separate plots
        fig, axes = plt.subplots(1, 2, figsize=(12, 6))

        # Utility boxplot
        axes[0].boxplot(utility_data, labels=labels, showfliers=False)
        axes[0].set_title(f'Utility (Budget={budget}, Variant={variant_mode})')
        axes[0].set_xlabel('Policy')
        axes[0].set_ylabel('Utility')
        axes[0].tick_params(axis='x', rotation=90)

        # Cost/Budget % boxplot
        axes[1].boxplot(cost_data, labels=labels, showfliers=False)
        axes[1].set_title(f'Cost/Budget % (Budget={budget}, Variant={variant_mode})')
        axes[1].set_xlabel('Policy')
        axes[1].set_ylabel('Cost/Budget %')
        axes[1].tick_params(axis='x', rotation=90)

        # Adjust layout and show plots
        plt.tight_layout()
        exp_scenario = input_file_name.split(".")[0]
        filename = f"{exp_scenario}_budget-{budget}_variant-{variant_mode}.png"
        save_path = os.path.join(output_folder, filename)
        #plt.savefig(save_path, dpi=300)
        plt.show()


def plot_boxplots_utility_co2(input_file_name, output_folder="plots_utility_co2"):
    csv_file = os.path.join(os.path.dirname(__file__), input_file_name)
    os.makedirs(output_folder, exist_ok=True)
    data = pd.read_csv(csv_file)

    # Ensure relevant columns exist
    required_columns = [cp.BUDGET, cp.VAR_MODE, cp.ALPHA, cp.BETA, cp.POLICY, cp.UTILITY, cp.CO2_EMISS_TOTAL, cp.SEED]

    # Group by budget and variant mode
    groups = data.groupby([cp.BUDGET, cp.VAR_MODE])

    for (budget, variant_mode), group_data in groups:
        # Create a dictionary to store data for plotting
        plot_data = {}

        for policy in group_data[cp.POLICY].unique():
            if policy == "probabilistic-carbon-aware":
                # For "probabilistic-carbon-aware," group by (alpha, beta) pairs
                grouped_by_policy = group_data[group_data[cp.POLICY] == policy].groupby([cp.ALPHA, cp.BETA])
                for (alpha, beta), sub_group in grouped_by_policy:
                    new_policy_name = f"{policy} ({alpha}, {beta})"
                    plot_data[new_policy_name] = sub_group
            else:
                # For other policies, group directly
                plot_data[policy] = group_data[group_data[cp.POLICY] == policy]

        # Prepare data for the two boxplots
        utility_co2_data = []  # Utility / CO2
        co2_utility_data = []  # CO2 / Utility
        labels = []

        for policy_name, sub_group in plot_data.items():
            # Group by seed and collect utility and CO2 emissions data
            grouped_by_seed = sub_group.groupby(cp.SEED)
            utility_values = grouped_by_seed[cp.UTILITY].mean().values
            co2_values = grouped_by_seed[cp.CO2_EMISS_TOTAL].mean().values

            utility_co2_values = utility_values / co2_values  # Utility / CO2
            co2_utility_values = co2_values / utility_values  # CO2 / Utility

            utility_co2_data.append(utility_co2_values)
            co2_utility_data.append(co2_utility_values)
            labels.append(policy_name)

        # Create two separate plots
        fig, axes = plt.subplots(1, 2, figsize=(12, 6))

        # Utility / CO2 Emissions boxplot
        axes[0].boxplot(utility_co2_data, labels=labels, showfliers=False)
        axes[0].set_title(f'Utility / CO2 Emissions (Budget={budget}, Variant={variant_mode})')
        axes[0].set_xlabel('Policy')
        axes[0].set_ylabel('Utility / CO2 Emissions')
        axes[0].tick_params(axis='x', rotation=90)

        # CO2 Emissions / Utility boxplot
        axes[1].boxplot(co2_utility_data, labels=labels, showfliers=False)
        axes[1].set_title(f'CO2 Emissions / Utility (Budget={budget}, Variant={variant_mode})')
        axes[1].set_xlabel('Policy')
        axes[1].set_ylabel('CO2 Emissions / Utility')
        axes[1].tick_params(axis='x', rotation=90)

        # Adjust layout and save plots
        plt.tight_layout()
        exp_scenario = input_file_name.split(".")[0]
        filename = f"{exp_scenario}_budget-{budget}_variant-{variant_mode}_utility_co2.png"
        save_path = os.path.join(output_folder, filename)
        #plt.savefig(save_path, dpi=300)
        plt.show()

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


# Usage example
if __name__ == "__main__":
    #input_file_name = "/home/cecilia/workspace/faas-offloading/050325_results_baseline/mainComparisonBrown_Baseline_1half.csv"
    #input_file_name = "/home/cecilia/workspace/faas-offloading/050325_results_baseline/mainComparisonGreen_Baseline_1half.csv"
    #input_file_name = "/home/cecilia/workspace/faas-offloading/050325_results_probabilistic/mainComparisonBrown_normalized_1half.csv"
    #input_file_name = "/home/cecilia/workspace/faas-offloading/050325_results_probabilistic/mainComparisonGreen_normalized.csv"
    #input_file_name = "/home/cecilia/workspace/faas-offloading/050325_results_probabilistic/mainComparisonBrown.csv"
    #input_file_name = "/home/cecilia/workspace/faas-offloading/050325_results_probabilistic/mainComparisonGreen.csv"
    #input_file_name = "/home/cecilia/workspace/faas-offloading/140325_results_probabilistic/mainComparisonBrown_temp.csv"
    #input_file_name = "/home/cecilia/workspace/faas-offloading/140325_results_probabilistic/mainComparisonBrown_1half.csv"
    #input_file_name = "/home/cecilia/workspace/faas-offloading/140325_results_probabilistic/mainComparisonBrown_normalized_1half.csv"
    #input_file_name = "/home/cecilia/workspace/faas-offloading/140325_results_probabilistic/mainComparisonGreen_1half.csv"
    input_file_name = "/home/cecilia/workspace/faas-offloading/140325_results_probabilistic/mainComparisonGreen_normalized_1half.csv"




    #mean_std(input_file_name)
    plot_boxplots(input_file_name)
    #plot_boxplots_cost(input_file_name)
    #plot_boxplots_cost_probabilistic_only(input_file_name)
    #plot_boxplots_utility_co2(input_file_name)
    #input_file_name = "200125_mainComparisonGreen_seedOK.csv"
    #plot_boxplots(input_file_name)
    #plot_boxplots_cost_probabilistic_only(input_file_name)
    #plot_boxplots_utility_co2(input_file_name)


