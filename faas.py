from dataclasses import dataclass,field




class ContainerPool:

    def __init__ (self):
        self.pool = []

    def append (self, e):
        self.pool.append(e)

    def remove (self, f):
        for entry in self.pool:
            if f.name == entry[0].name:
                self.pool.remove(entry)
                return

    def __len__ (self):
        return len(self.pool)

    def front (self):
        return self.pool[0]

    def reclaim_memory (self, required_mem):
        mem = [entry[0].memory for entry in self.pool]
        if sum(mem) < required_mem:
            return 0.0
        s = sorted([e[0] for e in self.pool], reverse=True, key = lambda x: x.memory)
        reclaimed = 0
        while reclaimed < required_mem:
            f = s[0]
            s = s[1:]
            self.remove(f)
            reclaimed += f.memory
        return reclaimed

    def __contains__ (self, f):
        if not isinstance(f, Function):
            return False
        for entry in self.pool:
            if f.name == entry[0].name:
                return True
        return False
    
    def __repr__ (self):
        return repr(self.pool)

class Node:
    def __init__(self, name, memory, speedup, region, co2_footprint,
                 processing_power_consumption,
                 tx_energy_consumption,
                 rx_energy_consumption,
                 cost=0.0, custom_sched_policy=None, peer_exposed_memory_fraction=1.0, g_co2_emissions = None):
        self.name = name
        self.total_memory = memory
        self.curr_memory = memory
        self.peer_exposed_memory_fraction = peer_exposed_memory_fraction
        self.speedup = speedup
        self.region = region
        self.cost = cost
        self.custom_sched_policy = custom_sched_policy

        self.warm_pool = ContainerPool()
        self.kv_store = {}

        self.co2_footprint = co2_footprint

        self.processing_power_consumption = processing_power_consumption #/ 1000   #kWatt
        self.tx_energy_consumption = tx_energy_consumption  / 1e9            #Joule/byte
        self.rx_energy_consumption = rx_energy_consumption  / 1e9
        self.g_co2_emissions = {}   #key: <function, schedulerDecision>, value: g CO2

    def __repr__(self):
        return self.name

    def __lt__(self, other):
        return self.name < other.name

    def __le__(self, other):
        return self.name <= other.name

    def __hash__(self):
        return hash(self.name)



class Dispatcher(Node):
    def __init__(self, name, memory, speedup, region, co2_footprint,
                 processing_power_consumption,
                 tx_energy_consumption,
                 rx_energy_consumption,
                 cost=0.0, custom_sched_policy="dispatcher-policy", peer_exposed_memory_fraction=0.0):

        super().__init__(name, memory, speedup, region, co2_footprint,
                         processing_power_consumption,
                         tx_energy_consumption,
                         rx_energy_consumption,
                         cost, custom_sched_policy, peer_exposed_memory_fraction)
        self.aggregated_region_memory = 0.0
        self.avg_speedup = 0.0
        self.aggregated_region_cost = 0.0

        self.avg_node2completions:dict = {}  #key= function, value = avg #completions
        self.avg_execution_time_sum:dict = {}    #key = function, value = avg exec time sum
        self.avg_cold_starts:dict = {}   #key = function, value = avg #cold starts

        self.avg_processing_power_consumption = 0.0
        self.avg_tx_energy_consumption = 0.0
        self.avg_rx_energy_consumption = 0.0


@dataclass
class QoSClass:
    name: str
    max_rt: float
    arrival_weight: float = 1.0
    utility: float = 1.0
    min_completion_percentage: float = 0.0
    deadline_penalty: float = 0.0
    drop_penalty: float = 0.0

    
    def __repr__ (self):
        return self.name

    def __hash__ (self):
        return hash(self.name)

    def __lt__(self, other):
        return self.name <  other.name

    def __le__(self,other):
        return self.name <= other.name


class Variant:
    def __init__(self, name, speedup, utility):
        self.name = name
        self.speedup = speedup
        self.utility = utility
        self.self_function = None

    def __repr__(self):
        return f"FunctionVariant(name={self.name}, speedup={self.speedup})"


@dataclass
class Function:
    name: str
    memory: int
    serviceMean: float
    serviceSCV: float = 1.0
    initMean: float = 0.500
    inputSizeMean: float = 100
    accessed_keys: [] = field(default_factory=lambda: [])
    max_data_access_time: float = None
    outputSizeMean: float = 10
    variants: [Variant] = field(default_factory=lambda: [])
    is_default: bool = False
    active_variant = None
    has_variants: bool = False
    speedup: float = 1.0
    
    def __repr__ (self):
        return self.name

    def __hash__ (self):
        return hash(self.name)

    def __lt__(self, other):
        return self.name <  other.name

    def __le__(self,other):
        return self.name <= other.name





@dataclass
class Container:
    function: Function
    expiration_time: float

    def __eq__ (self, other):
        if not isinstance(other, Container) and not isinstance(other, Function):
            return False
        elif isinstance(other, Function):
            return self.function == other.name
        else:
            return self.function == other.function



if __name__ == "__main__":
    pool = ContainerPool()
    f = Function("a", 200, 1, 1, 1)
    f2 = Function("b", 100, 1, 1, 1)
    pool.append((f,1))
    pool.append((f2,1))
    print(pool.pool)
    pool.reclaim_memory(500)
    print(pool.pool)
    pool.reclaim_memory(10)
    print(pool.pool)
