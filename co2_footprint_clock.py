class CO2footprint:
    def __init__(self,
                 node_name,
                 current_co2_footprint,
                 count,
                 is_increasing=True):
        self.node_name = node_name
        self.current_co2_footprint = current_co2_footprint
        self.count = count
        self.is_increasing = is_increasing
