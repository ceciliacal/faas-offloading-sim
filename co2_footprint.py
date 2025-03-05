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

m_u = 2048.0

def compute_local_energy(function, node, serv_time_local):
    #Compute the emitted co2 grams for a function processed locally.

    if node.curr_memory <= 0.0:
        return 0.0

    power_cons_local = node.processing_power_consumption
    m_f = function.memory
    co2_local = node.co2_footprint.co2_intensity

    return (
        (power_cons_local * float(m_f / m_u) * serv_time_local) *
        (1 / (3600 * 1000)) *
        float(co2_local)
    )


def compute_local_variant_energy(function_variant, node, serv_time_local_variant):
    #Compute the emitted co2 grams for a function variant processed locally.

    if node.curr_memory <= 0.0:
        return 0.0

    power_cons_variant = node.processing_power_consumption
    m_f = function_variant.memory
    co2_variant = node.co2_footprint.co2_intensity

    return (
            (power_cons_variant * float(m_f / m_u) * serv_time_local_variant) *
            (1 / (3600 * 1000)) *
            float(co2_variant)
    )


def compute_edge_energy(function, aggregated_edge_memory, aggregated_edge_power_consumption,
                        serv_time_edge, local_tx_energy, edge_rx_energy, local_rx_energy, edge_tx_energy, co2_edge):
    #Compute the emitted co2 grams for a function offloaded to the edge.

    if aggregated_edge_memory <= 0.0:
        return 0.0

    m_f = function.memory
    input_size_mean = function.inputSizeMean
    output_size_mean = function.outputSizeMean

    return (
        ((aggregated_edge_power_consumption * float(m_f / m_u) * serv_time_edge) +
         input_size_mean * (local_tx_energy + edge_rx_energy) +
         output_size_mean * (edge_tx_energy + local_rx_energy)) *
        (1 / (3600 * 1000)) *
        float(co2_edge)
    )


def compute_cloud_energy(function, dispatcher, serv_time_cloud, cloud_node, initial_node):
    #Compute the emitted co2 grams for a function offloaded to a specific cloud region.

    if dispatcher.aggregated_region_memory <= 0.0:
        return 0.0

    power_cons_cloud = dispatcher.avg_processing_power_consumption
    m_f = function.memory
    co2_cloud = dispatcher.co2_footprint.co2_intensity
    input_size_mean = function.inputSizeMean
    output_size_mean = function.outputSizeMean
    dispatcher_rx_energy = dispatcher.avg_rx_energy_consumption
    dispatcher_tx_energy = dispatcher.avg_tx_energy_consumption
    local_node_rx_energy = initial_node.rx_energy_consumption
    local_node_tx_energy = initial_node.tx_energy_consumption
    cloud_node_rx_energy = cloud_node.rx_energy_consumption
    cloud_node_tx_energy = cloud_node.tx_energy_consumption

    return (
        ((power_cons_cloud * float(m_f / m_u) * serv_time_cloud) +
         input_size_mean * (local_node_tx_energy + dispatcher_rx_energy) +
         input_size_mean * (dispatcher_tx_energy + cloud_node_rx_energy) +
         output_size_mean * (cloud_node_tx_energy + dispatcher_rx_energy)+
         output_size_mean * (dispatcher_tx_energy + local_node_rx_energy)) *
        #output_size_mean * (dispatcher_tx_energy + local_node_rx_energy)) *
        (1 / (3600 * 1000)) *
        float(co2_cloud)
    )
