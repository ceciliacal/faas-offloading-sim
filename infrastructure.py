import conf
from faas import Node

class Region:

    def __init__(self, name: str, co2_traces_filename, datetime_co2intensity, neighbors, latency_sec, bandwidth_mbps, default_cloud=None):
        self.name = name
        self.co2_traces_filename = co2_traces_filename
        self.datetime_co2intensity = datetime_co2intensity
        self.neighbors = neighbors #dict with Region as key
        self.latency_sec = latency_sec
        self.bandwidth_mbps = bandwidth_mbps

        self.default_cloud = default_cloud

    def __repr__(self):
        return (f"Region(name={self.name}, co2_traces_filename={self.co2_traces_filename}, "
                f"neighbors={self.neighbors}, latency_ms={self.latency_sec}, "
                f"bandwidth_mbps={self.bandwidth_mbps}), default_cloud={self.default_cloud}")


    def is_cloud (self):
        return self.default_cloud is None

    def __eq__ (self, other):
        return self.name == other.name

    def __hash__ (self):
        return hash(self.name)

    def __repr__ (self):
        return self.name

class Infrastructure:

    def __init__ (self, regions, network_latency: dict, bandwidth_mbps: dict):
        self.regions = [n for n in regions]
        self.latency = network_latency
        self.base_latency = network_latency
        self.bandwidth_mbps = bandwidth_mbps
        self.region_nodes = {r: []  for r in self.regions}
        self.region_dict = {r.name: r for r in self.regions}
        self.node2neighbors = {}

        self.cloud_regions = self.get_cloud_regions()
        self.edge_zones = self.get_edge_regions()
        self.num_regions_cloud = len(self.cloud_regions)
        self.num_edge_zones = len(self.edge_zones)
        self.region2neighbors = self.get_regions_neighbors(regions)
        self.set_region_neighbors(regions)

        self.cloud_nodes = []
        self.edge_nodes = []
        self.dispatchers = []

    def add_node_by_region_type(self, node):
        if node.region in self.cloud_regions:
            if node.curr_memory > 0:
                self.cloud_nodes.append(node)
            else:
                self.dispatchers.append(node)
        elif node.region in self.edge_zones:
            self.edge_nodes.append(node)

    def get_cloud_regions(self) -> [Region]:
        cloud_regions = []
        for region in self.regions:
            if region.is_cloud():
                cloud_regions.append(region)
        return cloud_regions

    def get_edge_regions(self) -> [Region]:
        edge_regions = []
        for region in self.regions:
            if not region.is_cloud():
                edge_regions.append(region)
        return edge_regions

    def get_regions_neighbors(self, regions_list:list):

        regions = {region.name: region for region in regions_list}
        # Initialize the proximity matrix with all values set to False
        regions_neighbors = {region_name: {other_region: False for other_region in regions} for region_name in regions}

        # Populate the matrix based on each region's neighbors
        for region_name, region in regions.items():
            # Determine the list of neighbors based on whether the region is cloud or edge
            neighbors_to_add = region.neighbors if region.is_cloud() else regions[region.default_cloud].neighbors
            neighbors_to_add = neighbors_to_add or []  # Default to empty list if neighbors_to_add is None

            for neighbor_name in neighbors_to_add:
                # Ensure the neighbor exists in the regions dictionary
                if neighbor_name in regions:
                    regions_neighbors[region_name][neighbor_name] = True
                    regions_neighbors[neighbor_name][region_name] = True

            # Link edge zones to their default cloud region
            if not region.is_cloud() and region.default_cloud in regions:
                regions_neighbors[region_name][region.default_cloud] = True
                regions_neighbors[region.default_cloud][region_name] = True

        return regions_neighbors

    def set_region_neighbors(self, regions_list:list):
        for region in regions_list:
            region.neighbors = self.region2neighbors[region.name]


    def get_latency (self, x: Node, y: Node):
        if x == y:
            # same node
            return 0.0

        if (x, y) in self.latency:
            return self.latency[(x, y)]
        elif (y, x) in self.latency:
            self.latency[(x,y)] = self.latency[(y, x)]
            return self.latency[(x, y)]
        else:
            return self.get_region_latency(x.region, y.region)


    def get_region_latency (self, x: Region, y: Region):
        if x == y and not (x,y) in self.latency:
            # same region default
            return 0.005

        if (x, y) in self.latency:
            return self.latency[(x, y)]
        elif (y, x) in self.latency:
            self.latency[(x,y)] = self.latency[(y, x)]
            return self.latency[(x, y)]

        raise KeyError(f"no latency specified for {x} and {y}")

    def get_bandwidth (self, x: Node, y: Node):
        if x == y:
            # same node
            return float("inf")

        if (x, y) in self.bandwidth_mbps:
            return self.bandwidth_mbps[(x, y)]
        elif (y, x) in self.bandwidth_mbps:
            self.bandwidth_mbps[(x,y)] = self.bandwidth_mbps[(y, x)]
            return self.bandwidth_mbps[(x, y)]
        else:
            return self.get_region_bandwidth(x.region, y.region)


    def get_region_bandwidth (self, x: Region, y: Region):
        if (x, y) in self.bandwidth_mbps:
            return self.bandwidth_mbps[(x, y)]
        elif (y, x) in self.bandwidth_mbps:
            self.bandwidth_mbps[(x,y)] = self.bandwidth_mbps[(y, x)]
            return self.bandwidth_mbps[(x, y)]

        raise KeyError(f"no bandwidth_mbps specified for {x} and {y}")

    def get_region (self, reg_name: str) -> Region:
        return self.region_dict[reg_name]

    def add_node (self, node, region: Region):
        self.region_nodes[region].append(node)

    def get_edge_nodes (self):
        nodes = []
        for r in self.edge_zones:
            reg_nodes = [n for n in self.region_nodes[r] if n.total_memory > 0]
            nodes.extend(reg_nodes)
        return nodes

    def get_cloud_nodes_by_region(self, r):
        return [n for n in self.region_nodes[r] if n.total_memory > 0]


    def get_cloud_nodes (self):
        nodes = []
        for r in self.cloud_regions:
            reg_nodes = [n for n in self.region_nodes[r] if n.total_memory > 0]
            nodes.extend(reg_nodes)

        return nodes

    def get_nodes (self, ignore_non_processing=True):
        nodes = []
        for r in self.regions:
            reg_nodes = [n for n in self.region_nodes[r] if n.total_memory*n.speedup > 0 or ignore_non_processing==False]
            nodes.extend(reg_nodes)
        return nodes

    def get_region_nodes(self, reg):
        return self.region_nodes[self.get_region(reg)]

    def get_nodes_by_region (self, reg):
        return self.region_nodes[reg]

    def get_neighbors_node (self, node, node_choice_rng, max_peers=2):
        if node in self.node2neighbors:
            peers = self.node2neighbors[node]
        else:
            peers = self.get_nodes_by_region(node.region).copy()
            peers.remove(node)
            self.node2neighbors[node] = peers

        if max_peers > 0 and len(peers) > max_peers:
            return node_choice_rng.choice(peers, max_peers)
        else:
            return peers

    def get_dispatcher_by_region_name(self, reg_name):
        for dispatcher in self.dispatchers:
            if dispatcher.region.name == reg_name:
                return dispatcher

    def __repr__ (self):
        s=""
        for r in self.regions:
            s += f"-------- {r} ({r.is_cloud()} - {r.default_cloud}) -------\n"
            for n in self.region_nodes[r]:
                s += repr(n) + "\n"
        return s



