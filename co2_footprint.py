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

    P = node.processing_power_consumption - node.idle_power_consumption
    m_f = function.memory
    co2_local = node.co2_footprint.co2_intensity

    return (
        (P * float(m_f / m_u) * serv_time_local) *
        (1 / (3600 * 1000)) *
        float(co2_local)
    )

def compute_edge_energy(function, aggregated_edge_memory, aggregated_edge_power_consumption,
                        aggregated_edge_idle_power_consumption, serv_time_edge, local_tx_energy,
                        edge_rx_energy, local_rx_energy, edge_tx_energy, co2_edge):
    #Compute the emitted co2 grams for a function offloaded to the edge.

    if aggregated_edge_memory <= 0.0:
        return 0.0

    P = aggregated_edge_power_consumption - aggregated_edge_idle_power_consumption
    m_f = function.memory

    return (
        ((P * float(m_f / m_u) * serv_time_edge ) +
         compute_transmission_energy_edge(function,
                                          local_tx_energy, local_rx_energy,
                                          edge_tx_energy, edge_rx_energy)) *
        (1 / (3600 * 1000)) *
        float(co2_edge)
    )


def compute_cloud_energy(function, dispatcher, serv_time_cloud, cloud_node, initial_node):
    #Compute the emitted co2 grams for a function offloaded to a specific cloud region.

    if dispatcher.aggregated_region_memory <= 0.0:
        return 0.0

    power_cons_cloud = dispatcher.avg_processing_power_consumption
    P = dispatcher.avg_processing_power_consumption - dispatcher.avg_idle_power_consumption
    m_f = function.memory
    co2_cloud = dispatcher.co2_footprint.co2_intensity

    return (
            ((P * float(m_f / m_u) * serv_time_cloud ) +
            compute_transmission_energy_cloud(function, dispatcher, initial_node, cloud_node)) *
            (1 / (3600 * 1000)) *
            float(co2_cloud)
    )


def compute_transmission_energy_cloud(function, dispatcher, initial_node, cloud_node):
    f_input_size = function.inputSizeMean
    f_output_size = function.outputSizeMean
    dispatcher_rx_power = dispatcher.avg_rx_power_consumption
    dispatcher_tx_power = dispatcher.avg_tx_power_consumption
    local_node_rx_power = initial_node.rx_power_consumption
    local_node_tx_power = initial_node.tx_power_consumption
    cloud_node_rx_power = cloud_node.rx_power_consumption
    cloud_node_tx_power = cloud_node.tx_power_consumption


    bandwidth_edge_cloud = 80.0
    bandwidth_cloud_cloud = 10000.0
    
    local_node_tx_energy = (local_node_tx_power / 1000) / bandwidth_edge_cloud
    local_node_rx_energy = (local_node_rx_power / 1000) / bandwidth_edge_cloud
    
    cloud_node_tx_energy = (cloud_node_tx_power / 1000) / bandwidth_cloud_cloud
    cloud_node_rx_energy = (cloud_node_rx_power / 1000) / bandwidth_cloud_cloud
    
    dispatcher_tx_energy = (dispatcher_tx_power / 1000) / bandwidth_edge_cloud
    dispatcher_rx_energy = (dispatcher_rx_power / 1000) / bandwidth_edge_cloud


    return (f_input_size * (8/1000/1000) * (local_node_tx_energy + dispatcher_rx_energy) +
    f_input_size * (8/1000/1000) * (dispatcher_tx_energy + cloud_node_rx_energy) +
    f_output_size * (8/1000/1000) * (cloud_node_tx_energy + dispatcher_rx_energy) +
    f_output_size * (8/1000/1000) * (dispatcher_tx_energy + local_node_rx_energy))

def compute_transmission_energy_edge(function,
                                     local_tx_power, local_rx_power,
                                     edge_tx_power, edge_rx_power):
    f_input_size = function.inputSizeMean
    f_output_size = function.outputSizeMean

    bandwidth = 100.0

    local_tx_energy = (local_tx_power / 1000)  / bandwidth
    local_rx_energy = (local_rx_power / 1000) / bandwidth
    edge_tx_energy = (edge_tx_power / 1000) / bandwidth
    edge_rx_energy = (edge_rx_power / 1000) / bandwidth

    return (f_input_size * (8/1000/1000) * (local_tx_energy + edge_rx_energy) +
    f_output_size * (8/1000/1000) * (edge_tx_energy + local_rx_energy))