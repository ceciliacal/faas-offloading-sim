from dataclasses import dataclass
from faas import Node, Function, QoSClass

@dataclass
class OptProblemParams:
    local_node: Node
    cloud: Node
    functions: [Function]
    classes: [QoSClass]
    arrival_rates: dict
    serv_time_local: dict
    serv_time_cloud: dict
    init_time_local: dict
    init_time_cloud: dict
    cold_start_p_local: dict
    cold_start_p_cloud: dict
    offload_time_cloud: float
    bandwidth_cloud: float = float("inf")
    usable_local_memory_coeff: float = 1.0
    budget: float = -1
    aggregated_edge_memory: float = 0
    serv_time_edge: dict = None
    offload_time_edge: float = 0
    cold_start_p_edge: dict = None
    init_time_edge: dict = None
    bandwidth_edge: float = float("inf")


    def fun_classes(self):
        for f in self.functions:
            for c in self.classes:
                yield (f,c)
