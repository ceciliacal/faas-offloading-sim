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

def function_processing_energy_consumption(node, function, serv_time):
    P = node.processing_power_consumption - node.idle_power_consumption
    m_f = function.memory
    return (P * float(m_f / m_u) * serv_time) # Watt * sec = Joule

def compute_local_emission(function, node, serv_time_local):
    if node.curr_memory <= 0.0:
        return 0.0
    
    co2_local = node.co2_footprint.co2_intensity
    
    return (
        function_processing_energy_consumption(node, function, serv_time_local) *
        (1 / (3600 * 1000)) *
        float(co2_local)
    )

def compute_virtual_edge_emission(function, aggregated_edge_memory, aggregated_edge_power_consumption,
                                  aggregated_edge_idle_power_consumption, serv_time_edge, local_tx_energy,
                                  edge_rx_energy, local_rx_energy, edge_tx_energy, co2_edge, edge_bandwidth):
    #Compute the emitted co2 grams for a function offloaded to the edge.

    if aggregated_edge_memory <= 0.0:
        return 0.0

    P = aggregated_edge_power_consumption - aggregated_edge_idle_power_consumption
    m_f = function.memory

    return (
            ((P * float(m_f / m_u) * serv_time_edge ) +
             compute_edge_transmission_energy(function, None, None, local_tx_energy, local_rx_energy, edge_tx_energy,
                                              edge_rx_energy, edge_bandwidth)) *
            (1 / (3600 * 1000)) *
            float(co2_edge)
    )

def compute_single_edge_emission(function, edge_peer, initial_node, serv_time_edge, edge_bandwidth):
    #Compute the emitted co2 grams for a function offloaded to the edge.

    if edge_peer.curr_memory <= 0.0:
        return 0.0

    co2_edge = edge_peer.co2_footprint.co2_intensity

    return (
        (function_processing_energy_consumption(edge_peer, function, serv_time_edge) +
            compute_edge_transmission_energy(function, initial_node, edge_peer, edge_bandwidth) )*
            (1 / (3600 * 1000)) *
            float(co2_edge)
    )

def compute_cloud_emission(function, dispatcher, serv_time_cloud, cloud_node, initial_node, cloud_edge_bandwidth=80.0):
    #Compute the emitted co2 grams for a function offloaded to a specific cloud region.

    if dispatcher.aggregated_region_memory <= 0.0:
        return 0.0

    co2_cloud = dispatcher.co2_footprint.co2_intensity

    return (
            (function_processing_energy_consumption(dispatcher, function, serv_time_cloud) +
             compute_cloud_transmission_energy(function, dispatcher, initial_node, cloud_node, cloud_edge_bandwidth)) *
            (1 / (3600 * 1000)) *
            float(co2_cloud)
    )

BANDWIDTH_EDGE_CLOUD = 80.0
BANDWIDTH_CLOUD_CLOUD = 10000.0
BANDWIDTH_EDGE_EDGE = 100.0

def compute_cloud_transmission_energy(function, dispatcher, initial_node, cloud_node, bandwidth_edge_cloud=80.0):
    f_input_size = function.inputSizeMean
    f_output_size = function.outputSizeMean
    dispatcher_rx_power = dispatcher.avg_rx_power_consumption
    dispatcher_tx_power = dispatcher.avg_tx_power_consumption
    local_node_rx_power = initial_node.rx_power_consumption
    local_node_tx_power = initial_node.tx_power_consumption
    cloud_node_rx_power = cloud_node.rx_power_consumption
    cloud_node_tx_power = cloud_node.tx_power_consumption
    
    local_node_tx_energy = (local_node_tx_power / 1000) / bandwidth_edge_cloud
    local_node_rx_energy = (local_node_rx_power / 1000) / bandwidth_edge_cloud
    
    cloud_node_tx_energy = (cloud_node_tx_power / 1000) / BANDWIDTH_CLOUD_CLOUD
    cloud_node_rx_energy = (cloud_node_rx_power / 1000) / BANDWIDTH_CLOUD_CLOUD
    
    dispatcher_tx_energy = (dispatcher_tx_power / 1000) / bandwidth_edge_cloud
    dispatcher_rx_energy = (dispatcher_rx_power / 1000) / bandwidth_edge_cloud


    return (f_input_size * (8/1000/1000) * (local_node_tx_energy + dispatcher_rx_energy) +
    f_input_size * (8/1000/1000) * (dispatcher_tx_energy + cloud_node_rx_energy) +
    f_output_size * (8/1000/1000) * (cloud_node_tx_energy + dispatcher_rx_energy) +
    f_output_size * (8/1000/1000) * (dispatcher_tx_energy + local_node_rx_energy))

def compute_edge_transmission_energy(function, initial_node, edge_node, local_node_rx_power=None,
                                     local_node_tx_power=None, edge_node_rx_power=None, edge_node_tx_power=None,
                                     edge_bandwidth=100.0):
    
    f_input_size = function.inputSizeMean
    f_output_size = function.outputSizeMean

    if local_node_rx_power is None:
        local_node_rx_power = initial_node.rx_power_consumption
    if local_node_tx_power is None:
        local_node_tx_power = initial_node.tx_power_consumption
    if edge_node_rx_power is None:
        edge_node_rx_power = edge_node.rx_power_consumption
    if edge_node_tx_power is None:
        edge_node_tx_power = edge_node.tx_power_consumption

    local_tx_energy = (local_node_tx_power / 1000)  / edge_bandwidth
    local_rx_energy = (local_node_rx_power / 1000) / edge_bandwidth
    edge_tx_energy = (edge_node_tx_power / 1000) / edge_bandwidth
    edge_rx_energy = (edge_node_rx_power / 1000) / edge_bandwidth

    return (f_input_size * (8/1000/1000) * (local_tx_energy + edge_rx_energy) +
    f_output_size * (8/1000/1000) * (edge_tx_energy + local_rx_energy))