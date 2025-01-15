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

def compute_local_energy(function, node, usable_local_memory_coeff, serv_time_local):
    """
    Compute the energy consumption for a function processed locally.
    """
    if node.curr_memory <= 0.0:
        return 0.0

    power_cons_local = node.processing_power_consumption
    m_f = function.memory
    m_u = usable_local_memory_coeff * node.curr_memory
    co2_local = node.co2_footprint.co2_intensity
    #print("[eP ",node,"] - f: ",function,"(power_cons_local * float(m_f / m_u) * serv_time_local) = ",(power_cons_local * float(m_f / m_u) * serv_time_local))
    #print("[eP ",node,"] - f: ",function,"(power_cons_local = ",(power_cons_local ))
    #print("[eP ", node, "] - f: ", function, "(float(m_f / m_u) = ", float(m_f / m_u)," mf= ",m_f," mu=",m_u)
    #print("[eP ", node, "] - f: ", function, "(serv_time_local = ", (serv_time_local))

    return (
        (power_cons_local * float(m_f / m_u) * serv_time_local) *
        (1 / (3600 * 1000)) *
        float(co2_local)
    )


def compute_local_variant_energy(function_variant, node, usable_local_memory_coeff, serv_time_local_variant):
    """
    Compute the energy consumption for a function variant processed locally.
    """
    if node.curr_memory <= 0.0:
        return 0.0

    power_cons_variant = node.processing_power_consumption
    m_f = function_variant.memory
    m_u = usable_local_memory_coeff * node.curr_memory
    co2_variant = node.co2_footprint.co2_intensity
    #print("[eP VAR ", node, "] - f: ", function_variant, "(power_cons_variant * float(m_f / m_u) * serv_time_local_variant) = ",
    #      (power_cons_variant * float(m_f / m_u) * serv_time_local_variant))
    #print("[eP VAR ", node, "] - f: ", function_variant, "(power_cons_local = ", (power_cons_variant))
    #print("[eP VAR ", node, "] - f: ", function_variant, "(float(m_f / m_u) = ", float(m_f / m_u), " mf= ", m_f, " mu=", m_u)
    #print("[eP VAR ", node, "] - f: ", function_variant, "(serv_time_local_variant = ", (serv_time_local_variant))
    return (
        (power_cons_variant * float( (m_f) / m_u) * serv_time_local_variant) *
        (1 / (3600 * 1000)) *
        float(co2_variant)
    )


def compute_edge_energy(function, aggregated_edge_memory, aggregated_edge_power_consumption,
                        serv_time_edge, local_tx_energy, edge_rx_energy, local_rx_energy, edge_tx_energy, co2_edge):
    """
    Compute the energy consumption for a function offloaded to the edge.
    """
    if aggregated_edge_memory <= 0.0:
        return 0.0

    m_f = function.memory
    m_e = aggregated_edge_memory
    input_size_mean = function.inputSizeMean
    output_size_mean = function.outputSizeMean

    return (
        ((aggregated_edge_power_consumption * float(m_f / m_e) * serv_time_edge) +
         input_size_mean * (local_tx_energy + edge_rx_energy) +
         output_size_mean * (edge_tx_energy + local_rx_energy)) *
        (1 / (3600 * 1000)) *
        float(co2_edge)
    )


def compute_cloud_energy(function, dispatcher, serv_time_cloud, local_tx_energy, local_rx_energy):
    """
    Compute the energy consumption for a function offloaded to a specific cloud region.
    """
    if dispatcher.aggregated_region_memory <= 0.0:
        return 0.0

    power_cons_cloud = dispatcher.avg_processing_power_consumption
    m_f = function.memory
    m_c = dispatcher.aggregated_region_memory
    co2_cloud = dispatcher.co2_footprint.co2_intensity
    input_size_mean = function.inputSizeMean
    output_size_mean = function.outputSizeMean
    cloud_rx_energy = dispatcher.avg_rx_energy_consumption
    cloud_tx_energy = dispatcher.avg_tx_energy_consumption

    #print("[eP ",dispatcher,"] - f: ",function,"(power_cons_cloud * float(m_f / m_c) * serv_time_cloud) = ",(power_cons_cloud * float(m_f / m_c) * serv_time_cloud))
    #print("[eP ",dispatcher,"] - f: ",function,"offloading part = ",input_size_mean * (local_tx_energy + cloud_rx_energy) +output_size_mean * (cloud_tx_energy + local_rx_energy))
    #print("[eP ",dispatcher,"] - power_cons_cloud: ", power_cons_cloud)
    #print("[eP ",dispatcher,"] - float(m_f / m_c): ", float(m_f / m_c)," mf: ",m_f," mc=",m_c)
    #print("[eP ",dispatcher,"] - serv_time_cloud: ", serv_time_cloud)

    return (
        ((power_cons_cloud * float(m_f / m_c) * serv_time_cloud) +
         input_size_mean * (local_tx_energy + cloud_rx_energy) +
         output_size_mean * (cloud_tx_energy + local_rx_energy)) *
        (1 / (3600 * 1000)) *
        float(co2_cloud)
    )
