class CO2footprint:
    def __init__(self,
                 node_name,
                 co2_datetime=None,
                 co2_intensity = 0.0,
                 count = 0):
        self.node_name = node_name
        self.co2_datetime = co2_datetime
        self.co2_intensity = co2_intensity
        self.count = count

    def __repr__(self):
        return (
            f"CO2footprint("
            f"node_name='{self.node_name}', "
            f"co2_datetime={self.co2_datetime}, "
            f"co2_intensity={self.co2_intensity}, "
            f"count={self.count})"
        )
