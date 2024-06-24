class Battery:
    def __init__(self, node_name, soc, time_consumption_rate,
                 recharge_input, battery_capacity,
                 idle_node_power_consumption_rate,
                 resources_consumption_rate,
                 offloading_consumption_rate):
        self.node_name = node_name

        #node's battery
        self.full_capacity = battery_capacity  #mAh/second
        self.current_capacity = self.full_capacity
        self.soc = soc  # battery depletion simulation
        self.idle_soc_depletion = ((idle_node_power_consumption_rate * time_consumption_rate * 100) /
                                   self.full_capacity)  # SoC depletion every 1 sec
        self.depletion_interval = time_consumption_rate  # soc update interval (1 sec)

        #node's energy consumption
        self.resources_soc_depletion = (resources_consumption_rate * time_consumption_rate * 100) / self.full_capacity
        self.offloading_soc_depletion = (offloading_consumption_rate * time_consumption_rate * 100) / self.full_capacity

        self.energy_consumption = 0  #e_u (node energy consumption)
        self.recharge_input = recharge_input  # energy input recharge rate

    #todo. aggiungere spegnimento nodo se soc = 0
    def update_soc_idle(self):
        self.soc = self.soc - self.idle_soc_depletion
        print("===soc: ", self.soc, " nodo ", self.node_name, " self.idle_soc_depletion ", self.idle_soc_depletion)
        return self.soc

    def update_soc_completion(self, function_memory, node_memory):
        soc_completion = (function_memory / node_memory) * self.resources_soc_depletion
        self.soc = self.soc - soc_completion
        print("===soc completion: ", soc_completion, "===soc: ", self.soc, " nodo ", self.node_name,
              "  function_memory: ", function_memory, " node_memory: ", node_memory)
        return self.soc

    def update_soc_offloading(self, data_size):
        soc_offloading = data_size * self.offloading_soc_depletion
        self.soc = self.soc - soc_offloading
        print("===soc_offloading: ", soc_offloading, "===soc: ", self.soc, " nodo ", self.node_name,
              "  data_size: ", data_size)
        return self.soc
