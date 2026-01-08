from dataclasses import dataclass
from faas import Node, Function, QoSClass

@dataclass
class OptCarbonAwareProblemParams:
    local_node: Node
    cloud_regions_dispatchers: dict #dispatchers dictionary
    possible_decisions: list
    functions: [Function]
    classes: [QoSClass]
    variants: dict
    arrival_rates: dict
    serv_time_local: dict
    serv_time_cloud: dict
    init_time_local: dict
    init_time_cloud: dict
    cold_start_p_local: dict
    cold_start_p_cloud: dict
    offload_time_cloud: dict #rtt cloud
    bandwidth_cloud: dict
    usable_local_memory_coeff: float = 1.0
    budget: float = -1
    aggregated_edge_memory: float = 0
    serv_time_edge: dict = None
    offload_time_edge: float = 0
    cold_start_p_edge: dict = None
    init_time_edge: dict = None
    bandwidth_edge: float = float("inf")
    aggregated_edge_power_consumption: float = float("inf")
    aggregated_edge_energy_tx: float = float("inf")
    aggregated_edge_energy_rx: float = float("inf")
    co2_green_threshold: float = float("inf")
    alpha: float = 0.0
    beta: float = 0.0
    t: float = 0.0
    utilization_LP_dict: dict = None,
    energy_LP_dict: dict = None,
    aggregated_edge_idle_power_consumption: float = float("inf")


    def fun_classes(self):
        for f in self.functions:
            for c in self.classes:
                yield (f,c)

