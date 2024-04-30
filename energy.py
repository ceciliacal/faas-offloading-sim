class Energy:
    def __init__(self, soc, recharge_rate,
                 battery_capacity, power_consumption_rate_idle, power_consumption_rate_max):
        #node's battery
        self.full_capacity = battery_capacity
        self.idle_consumption_rate = power_consumption_rate_idle  #mAh/second

        self.current_capacity = self.full_capacity
        self.soc = soc  #battery depletion simulation

        #node's energy consumption
        self.max_consumption_rate = power_consumption_rate_max
        self.energy_consumption = 0  #e_u (node energy consumption)
        self.recharge_rate = recharge_rate  # energy input recharge rate

    def update_soc_idle(self, node_name):  #t è tempo dell'evento in cui viene chiamata soc
        #mi serve pure il tempo t in input
        self.current_capacity = self.current_capacity - self.idle_consumption_rate
        self.soc = self.current_capacity / self.full_capacity
        print("===soc: ", self.soc, " nodo ", node_name)
        return self.soc
