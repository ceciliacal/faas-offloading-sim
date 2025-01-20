import os
import matplotlib.pyplot as plt
import pandas as pd
import conf_plots as cp


def plot_boxplots(csv_file):
    # Read the CSV file
    data = pd.read_csv(csv_file)

    # Ensure relevant columns exist
    required_columns = [cp.BUDGET, cp.VAR_MODE, cp.ALPHA, cp.BETA, cp.POLICY, cp.UTILITY, cp.CO2_EMISS_TOTAL, cp.SEED]
    if not all(col in data.columns for col in required_columns):
        raise ValueError(f"The CSV file must contain the following columns: {required_columns}")

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

        # Prepare data for utility and CO2 emissions boxplots
        utility_data = []
        co2_data = []
        labels = []

        for policy_name, sub_group in plot_data.items():
            # Group by seed and collect utility and CO2 emissions data
            grouped_by_seed = sub_group.groupby(cp.SEED)
            utility_values = grouped_by_seed[cp.UTILITY].mean().values
            co2_values = grouped_by_seed[cp.CO2_EMISS_TOTAL].mean().values

            utility_data.append(utility_values)
            co2_data.append(co2_values)
            labels.append(policy_name)

        # Create two separate plots
        fig, axes = plt.subplots(1, 2, figsize=(12, 6))

        # Utility boxplot
        axes[0].boxplot(utility_data, labels=labels, showmeans=True)
        axes[0].set_title(f'Utility (Budget={budget}, Variant={variant_mode})')
        axes[0].set_xlabel('Policy')
        axes[0].set_ylabel('Utility')
        axes[0].tick_params(axis='x', rotation=45)

        # CO2 Emissions boxplot
        axes[1].boxplot(co2_data, labels=labels, showmeans=True)
        axes[1].set_title(f'CO2 Emissions (Budget={budget}, Variant={variant_mode})')
        axes[1].set_xlabel('Policy')
        axes[1].set_ylabel('CO2 Emissions')
        axes[1].tick_params(axis='x', rotation=45)

        # Adjust layout and show plots
        plt.tight_layout()
        plt.show()


# Usage example
if __name__ == "__main__":
    curr_csv_file_path = "mainComparisonBrown.csv"
    my_data = os.path.join(os.path.dirname(__file__), curr_csv_file_path)
    plot_boxplots(my_data)


