SEC_CONTAINER = "container"
EXPIRATION_TIMEOUT = "expiration-timeout"

SEC_SIM = "simulation"
SEED = "seed"
CLOSE_DOOR_TIME = "close-door-time"
PLOT_RESP_TIMES = "plot-rt"
STAT_PRINT_INTERVAL = "stats-print-interval"
STAT_PRINT_FILE = "stats-print-file"
PRINT_FINAL_STATS = "print-final-stats"
SPEC_FILE = "spec-file"
EDGE_NEIGHBORS = "edge-neighbors"
EDGE_EXPOSED_FRACTION = "edge-exposed-fraction"
RESP_TIMES_FILE = "resp-times-file"
VERBOSITY = "verbosity"
RATE_UPDATE_INTERVAL = "rate-update-interval"

SEC_POLICY = "policy"
POLICY_NAME = "name"
POLICY_UPDATE_INTERVAL = "update-interval"
POLICY_ARRIVAL_RATE_ALPHA = "arrival-alpha"
ADAPTIVE_LOCAL_MEMORY = "adaptive-local-memory"
EDGE_OFFLOADING_ENABLED = "edge-offloading-enabled"
LOCAL_COLD_START_EST_STRATEGY = "local-cold-start-estimation"
CLOUD_COLD_START_EST_STRATEGY = "cloud-cold-start-estimation"
EDGE_COLD_START_EST_STRATEGY = "edge-cold-start-estimation"
HOURLY_BUDGET = "budget"
QOS_OPTIMIZER = "optimizer"
SPLIT_BUDGET_AMONG_EDGE_NODES = "split-budget-edge"
MULTIPLE_OFFLOADING_ALLOWED = "multiple-offloading-allowed"
FALLBACK_ON_LOCAL_REJECTION = "local-rejection-fallback"

SEC_STATEFUL = "stateful"

SEC_BATTERY = "battery"
BATTERY_UPDATE_INTERVAL = "update-interval"
ENERGY_PER_DATA_SIZE = "energy-per-data-size"
CO2_EMISSION_UPDATE_INTERVAL = "co2-emission-update-interval"
CO2_EMISSION_NUMBER_UPDATES = "co2-emission-number-updates"

SEC_CARBON = "carbon"
CARBON_INTENSITY_UPDATE_INTERVAL = "update-interval"
NUM_REGIONS_CLOUD = "num-regions-cloud"
NUM_REGIONS_EDGE = "num-regions-edge"
START_DATE = "start-date"
END_DATE = "end-date"
FILE_CO2_TRACES_EDGE_REGION_1 = "file-edge1"
FILE_CO2_TRACES_EDGE_REGION_2 = "file-edge2"
FILE_CO2_TRACES_CLOUD_REGION_1 = "file-cloud1"
FILE_CO2_TRACES_CLOUD_REGION_2 = "file-cloud2"
CO2_TRACES_COL_TIMESTAMP= "Datetime (UTC)"
CO2_TRACES_COL_INTENSITY_DIRECT = "Carbon Intensity gCO₂eq/kWh (direct)"
REGIONS_FILE = "regions-file"

EDGE = "edge"
CLOUD = "cloud"
LOCAL = "local"
EDGE_NEIGHBORS_PER_REGION = "edge_neighbors_per_region"
DISPATCHER = "dispatcher"
EXEC = "EXEC"
DROP = "DROP"
OFFLOAD_CLOUD_DECISION = "OFFLOAD_CLOUD_"

ENABLE_VARIANTS = "ENABLE_VARIANTS"

import configparser

def parse_config_file(config_file):
    config = configparser.ConfigParser()
    config.read(config_file)
    return config
