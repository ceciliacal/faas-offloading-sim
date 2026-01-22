import json
import os

import yaml
import tempfile
from scipy.stats import truncnorm
import numpy as np
import map as MAP

ARRIVAL_DISTRIBUTIONS = ["exp","mmpp","erlang","hyper"]

# Returns an open NamedTemporaryFile
def generate_temp_spec (n_functions=1, load_coeff=1.0, dynamic_rate_coeff=1.0, arrivals_to_single_node=True,
                   n_classes=1, cloud_cost=0.00005, cloud_speedup=1.0, n_edges=5):

    classes = [{'name': 'critical', 'max_resp_time': 0.5, 'utility': 1.0, 'arrival_weight': 1.0}, {'name': 'standard', 'max_resp_time': 0.5, 'utility': 0.01, 'arrival_weight': 7.0}, {'name': 'batch', 'max_resp_time': 99.0, 'utility': 1.0, 'arrival_weight': 1.0}, {'name': 'criticalP', 'max_resp_time': 0.5, 'utility': 1.0, 'penalty': 0.75, 'arrival_weight': 1.0}]
    nodes = [{'name': 'edge1', 'region': 'edge', 'memory': 4096}, {'name': 'edge2', 'region': 'edge', 'memory': 4096}, {'name': 'edge3', 'region': 'edge', 'memory': 4096}, {'name': 'edge4', 'region': 'edge', 'memory': 4096}, {'name': 'edge5', 'region': 'edge', 'memory': 4096}, {'name': 'cloud1', 'region': 'cloud', 'cost': cloud_cost, 'speedup': cloud_speedup, 'memory': 8192}]
    functions = [{'name': 'f1', 'memory': 512, 'duration_mean': 0.4, 'duration_scv': 1.0, 'init_mean': 0.5}, {'name': 'f2', 'memory': 512, 'duration_mean': 0.2, 'duration_scv': 1.0, 'init_mean': 0.25}, {'name': 'f3', 'memory': 128, 'duration_mean': 0.3, 'duration_scv': 1.0, 'init_mean': 0.6}, {'name': 'f4', 'memory': 1024, 'duration_mean': 0.25, 'duration_scv': 1.0, 'init_mean': 0.25}, {'name': 'f5', 'memory': 256, 'duration_mean': 0.45, 'duration_scv': 1.0, 'init_mean': 0.5}]

    #Extend functions list if needed
    if n_functions > len(functions):
        i=0
        while n_functions > len(functions):
            new_f = functions[i].copy()
            new_f["name"] = f"f{len(functions)+1}"
            functions.append(new_f)
            i+=1
    else:
        functions = functions[:n_functions]
    function_names = [f["name"] for f in functions]

    #Extend node list if needed
    if n_edges > len(nodes) - 1:
        i=0
        while n_edges > len(nodes) - 1:
            new_f = nodes[0].copy()
            new_f["name"] = f"nedge{i}"
            nodes.append(new_f)
            i+=1
    elif n_edges < len(nodes) - 1:
        new_nodes = nodes[:n_edges]
        new_nodes.append(nodes[-1])
        nodes = new_nodes

    #Extend class list if needed
    if n_classes > len(classes):
        i=0
        while n_classes > len(classes):
            new_f = classes[i].copy()
            new_f["name"] = f"c{len(classes)+1}"
            classes.append(new_f)
            i+=1
    else:
        classes = classes[:n_classes]

    ntemp = tempfile.NamedTemporaryFile(mode="w")
    write_spec(ntemp, functions, classes, nodes, load_coeff, dynamic_rate_coeff, arrivals_to_single_node)
    return ntemp

def generate_random_temp_spec (rng, n_functions=5, load_coeff=1.0, dynamic_rate_coeff=1.0, arrivals_to_single_node=True,
                   n_classes=4, cloud_cost=0.00005, cloud_speedup=1.0, n_edges=5):

    classes = [{'name': 'critical', 'max_resp_time': 0.5, 'utility': 1.0, 'arrival_weight': 1.0}, {'name': 'standard', 'max_resp_time': 0.5, 'utility': 0.01, 'arrival_weight': 7.0}, {'name': 'batch', 'max_resp_time': 99.0, 'utility': 1.0, 'arrival_weight': 1.0}, {'name': 'criticalP', 'max_resp_time': 0.5, 'utility': 1.0, 'penalty': 0.75, 'arrival_weight': 1.0}]
    nodes = [{'name': 'edge1', 'region': 'edge', 'memory': 4096}, {'name': 'edge2', 'region': 'edge', 'memory': 4096}, {'name': 'edge3', 'region': 'edge', 'memory': 4096}, {'name': 'edge4', 'region': 'edge', 'memory': 4096}, {'name': 'edge5', 'region': 'edge', 'memory': 4096}, {'name': 'cloud1', 'region': 'cloud', 'cost': cloud_cost, 'speedup': cloud_speedup, 'memory': 8192}]
    functions = [{'name': 'f1', 'memory': 512, 'duration_mean': 0.4, 'duration_scv': 1.0, 'init_mean': 0.5}, {'name': 'f2', 'memory': 512, 'duration_mean': 0.2, 'duration_scv': 1.0, 'init_mean': 0.25}, {'name': 'f3', 'memory': 128, 'duration_mean': 0.3, 'duration_scv': 1.0, 'init_mean': 0.6}, {'name': 'f4', 'memory': 1024, 'duration_mean': 0.25, 'duration_scv': 1.0, 'init_mean': 0.25}, {'name': 'f5', 'memory': 256, 'duration_mean': 0.45, 'duration_scv': 1.0, 'init_mean': 0.5}]
   
    #Extend functions list if needed
    if n_functions > len(functions):
        i=0
        while n_functions > len(functions):
            new_f = functions[i].copy()
            new_f["name"] = f"f{len(functions)+1}"
            functions.append(new_f)
            i+=1
    else:
        functions = functions[:n_functions]
    function_names = [f["name"] for f in functions]

    #Extend node list if needed
    if n_edges > len(nodes) - 1:
        i=0
        while n_edges > len(nodes) - 1:
            new_f = nodes[0].copy()
            new_f["name"] = f"nedge{i}"
            nodes.append(new_f)
            i+=1
    elif n_edges < len(nodes) - 1:
        new_nodes = nodes[:n_edges]
        new_nodes.append(nodes[-1])
        nodes = new_nodes

    #Extend class list if needed
    if n_classes > len(classes):
        i=0
        while n_classes > len(classes):
            new_f = classes[i].copy()
            new_f["name"] = f"c{len(classes)+1}"
            classes.append(new_f)
            i+=1
    else:
        classes = classes[:n_classes]



    # Randomly set specs
    for f in functions:
        f["duration_mean"] = float(rng.uniform(0.1,0.5))
        f["init_mean"] = float(rng.uniform(0.25,0.75))
        f["memory"] = float(rng.uniform(128,1024))
        f["duration_scv"] = float(rng.choice([1,0.5,0.25]))

        myclip_a = 100
        myclip_b = 1024*1024*5
        loc = 1024
        scale = 10**3
        a, b = (myclip_a - loc) / scale, (myclip_b - loc) / scale
        f["input_mean"] = float(truncnorm.rvs(a, b, loc=loc, scale=scale, size=1))

    if dynamic_rate_coeff > 1.0:
        print("Forcing Poisson arrivals")
        functions_arrival_distributions = {f["name"]: "exp" for f in functions}
    else:
        functions_arrival_distributions = rng.choice(ARRIVAL_DISTRIBUTIONS, size=n_functions)
        functions_arrival_distributions = {f["name"]: d for f,d in zip(functions, functions_arrival_distributions)}


    ntemp = tempfile.NamedTemporaryFile(mode="w")
    write_spec(ntemp, functions, classes, nodes, load_coeff, dynamic_rate_coeff, arrivals_to_single_node, functions_arrival_distributions=functions_arrival_distributions)
    return ntemp

#variants mode: 0 inactive, 1 active with speedup=utility for each variants
def generate_random_temp_spec_variants(rng, n_functions=5, variants_mode=0, n_variants=2, load_coeff=1.0, dynamic_rate_coeff=1.0, arrivals_to_single_node=False,
                              n_classes=2, cloud_cost_reg_a=0.00001, cloud_cost_reg_b=0.00001, cloud_speedup=1.0):
    classes = [
        {'name': 'critical', 'max_resp_time': 0.5, 'utility': 1.0, 'arrival_weight': 3.0},
        {'name': 'standard', 'max_resp_time': 0.5, 'utility': 0.01, 'arrival_weight': 7.0}
    ]
    functions = [{'name': 'f1', 'memory': 512, 'duration_mean': 0.4, 'duration_scv': 1.0, 'init_mean': 0.5}, {'name': 'f2', 'memory': 512, 'duration_mean': 0.2, 'duration_scv': 1.0, 'init_mean': 0.25}, {'name': 'f3', 'memory': 128, 'duration_mean': 0.3, 'duration_scv': 1.0, 'init_mean': 0.6}, {'name': 'f4', 'memory': 1024, 'duration_mean': 0.25, 'duration_scv': 1.0, 'init_mean': 0.25}, {'name': 'f5', 'memory': 256, 'duration_mean': 0.45, 'duration_scv': 1.0, 'init_mean': 0.5}]

    nodes = [
        {'name': 'edge_node_a', 'region': 'edge_zone_1', 'memory': 3072,
         'processing_power_consumption': 75.0, 'idle_power_consumption': 15.0,
         'tx_power_consumption': 300.0, 'rx_power_consumption': 300.0},
        
        {'name': 'edge_node_b', 'region': 'edge_zone_1', 'memory': 3072,
         'processing_power_consumption': 75.0, 'idle_power_consumption': 15.0,
         'tx_power_consumption': 300.0, 'rx_power_consumption': 300.0},
        
        {'name': 'edge_node_c', 'region': 'edge_zone_1', 'memory': 3072,
         'processing_power_consumption': 75.0, 'idle_power_consumption': 15.0,
         'tx_power_consumption': 300.0, 'rx_power_consumption': 300.0},
        
        {'name': 'cloud_node_a', 'region': 'cloud_region_a', 'cost': cloud_cost_reg_a, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},
        
        {'name': 'cloud_node_a1', 'region': 'cloud_region_a', 'cost': cloud_cost_reg_a, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},
        
        {'name': 'cloud_node_a2', 'region': 'cloud_region_a', 'cost': cloud_cost_reg_a, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},
        
        {'name': 'cloud_node_a3', 'region': 'cloud_region_a', 'cost': cloud_cost_reg_a, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},
        
        {'name': 'cloud_node_a4', 'region': 'cloud_region_a', 'cost': cloud_cost_reg_a, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},
        
        {'name': 'cloud_node_a5', 'region': 'cloud_region_a', 'cost': cloud_cost_reg_a, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},
        
        {'name': 'cloud_node_a6', 'region': 'cloud_region_a', 'cost': cloud_cost_reg_a, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},
        
        {'name': 'cloud_node_b', 'region': 'cloud_region_b', 'cost': cloud_cost_reg_b, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},
        
        {'name': 'cloud_node_b1', 'region': 'cloud_region_b', 'cost': cloud_cost_reg_b, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},
        
        {'name': 'cloud_node_b2', 'region': 'cloud_region_b', 'cost': cloud_cost_reg_b, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},
        
        {'name': 'cloud_node_b3', 'region': 'cloud_region_b', 'cost': cloud_cost_reg_b, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},
        
        {'name': 'cloud_node_b4', 'region': 'cloud_region_b', 'cost': cloud_cost_reg_b, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},
        
        {'name': 'cloud_node_b5', 'region': 'cloud_region_b', 'cost': cloud_cost_reg_b, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},
        
        {'name': 'cloud_node_b6', 'region': 'cloud_region_b', 'cost': cloud_cost_reg_b, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},

        {'name': 'cloud_node_c', 'region': 'cloud_region_c', 'cost': 0.00002, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},

        {'name': 'cloud_node_c1', 'region': 'cloud_region_c', 'cost': 0.00002, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},

        {'name': 'cloud_node_c2', 'region': 'cloud_region_c', 'cost': 0.00002, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},

        {'name': 'cloud_node_c3', 'region': 'cloud_region_c', 'cost': 0.00002, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},

        {'name': 'cloud_node_c4', 'region': 'cloud_region_c', 'cost': 0.00002, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},

        {'name': 'cloud_node_c5', 'region': 'cloud_region_c', 'cost': 0.00002, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},

        {'name': 'cloud_node_c6', 'region': 'cloud_region_c', 'cost': 0.00002, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 327.0, 'idle_power_consumption': 120.0, 'tx_power_consumption': 5000.0, 'rx_power_consumption': 5000.0},

        {'name': 'dispatcher_a', 'region': 'cloud_region_a', 'memory': 0, 'policy': 'dispatcher-policy'},
        {'name': 'dispatcher_b', 'region': 'cloud_region_b', 'memory': 0, 'policy': 'dispatcher-policy'},
        {'name': 'dispatcher_c', 'region': 'cloud_region_c', 'memory': 0, 'policy': 'dispatcher-policy'}
    ]

    # Extend functions list if needed
    if n_functions > len(functions):
        i = 0
        while n_functions > len(functions):
            new_f = functions[i].copy()
            new_f["name"] = f"f{len(functions) + 1}"
            functions.append(new_f)
            i += 1
    else:
        functions = functions[:n_functions]
    function_names = [f["name"] for f in functions]

    # Extend class list if needed
    if n_classes > len(classes):
        i = 0
        while n_classes > len(classes):
            new_f = classes[i].copy()
            new_f["name"] = f"c{len(classes) + 1}"
            classes.append(new_f)
            i += 1
    else:
        classes = classes[:n_classes]

    # Randomly set specs
    for f in functions:
        f["duration_mean"] = float(rng.uniform(0.05, 0.5))
        f["init_mean"] = float(rng.uniform(0.1, 0.5))
        f["memory"] = float(rng.uniform(128, 512))
        f["duration_scv"] = float(rng.choice([1, 0.5, 0.25]))
        f["input_mean"] = float(rng.uniform(100, 5 * 1024 * 1024))

        myclip_a = 100
        myclip_b = 1024 * 1024 * 5
        loc = 1024
        scale = 10 ** 3
        a, b = (myclip_a - loc) / scale, (myclip_b - loc) / scale
        f["input_mean"] = float(truncnorm.rvs(a, b, loc=loc, scale=scale, size=1))

        f["speedup"] = [1.0]
        f["utility"] = [1.0]

        if variants_mode == 1:
            f["speedup"].extend(float(rng.uniform(0.25, 0.85)) for _ in range(n_variants - 1))
            f["utility"].extend(f["speedup"][1:])


    #functions_arrival_distributions = {f["name"]: "exp" for f in functions}


    if dynamic_rate_coeff > 1.0:
        print("Forcing Poisson arrivals")
        functions_arrival_distributions = {f["name"]: "exp" for f in functions}
    else:
        functions_arrival_distributions = rng.choice(ARRIVAL_DISTRIBUTIONS, size=n_functions)
        functions_arrival_distributions = {f["name"]: d for f, d in zip(functions, functions_arrival_distributions)}


    ntemp = tempfile.NamedTemporaryFile(mode="w")
    write_spec(ntemp, functions, classes, nodes, load_coeff, dynamic_rate_coeff, arrivals_to_single_node,
               functions_arrival_distributions=functions_arrival_distributions)

    return ntemp


def generate_random_temp_spec_variants2(rng, n_functions=5, variants_mode=0, n_variants=2, load_coeff=1.0, dynamic_rate_coeff=1.0, arrivals_to_single_node=False,
                              n_classes=2, cloud_cost_reg_a=0.00001, cloud_cost_reg_b=0.00001, seed=1):
    classes = [
        {'name': 'critical', 'max_resp_time': 0.5, 'utility': 1.0, 'arrival_weight': 1.0},
        {'name': 'standard', 'max_resp_time': 0.5, 'utility': 0.01, 'arrival_weight': 7.0}
    ]
    functions = [{'name': 'f1', 'memory': 512, 'duration_mean': 0.4, 'duration_scv': 1.0, 'init_mean': 0.5},
                 {'name': 'f2', 'memory': 512, 'duration_mean': 0.2, 'duration_scv': 1.0, 'init_mean': 0.25},
                 {'name': 'f3', 'memory': 128, 'duration_mean': 0.3, 'duration_scv': 1.0, 'init_mean': 0.6},
                 {'name': 'f4', 'memory': 1024, 'duration_mean': 0.25, 'duration_scv': 1.0, 'init_mean': 0.25},
                 {'name': 'f5', 'memory': 256, 'duration_mean': 0.45, 'duration_scv': 1.0, 'init_mean': 0.5}]

    nodes = [
        {'name': 'edge_node_a', 'region': 'edge_zone_1', 'memory': 3072,
         'processing_power_consumption': 100.0, 'tx_energy_consumption': 50.0, 'rx_energy_consumption': 30.0},
        {'name': 'edge_node_b', 'region': 'edge_zone_1', 'memory': 3072,
         'processing_power_consumption': 100.0, 'tx_energy_consumption': 50.0, 'rx_energy_consumption': 30.0},
        {'name': 'edge_node_c', 'region': 'edge_zone_1', 'memory': 3072,
         'processing_power_consumption': 100.0, 'tx_energy_consumption': 50.0, 'rx_energy_consumption': 30.0},
        {'name': 'cloud_node_a', 'region': 'cloud_region_a', 'cost': cloud_cost_reg_a, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 800.0, 'tx_energy_consumption': 5.0, 'rx_energy_consumption': 3.0},
        {'name': 'cloud_node_b', 'region': 'cloud_region_b', 'cost': cloud_cost_reg_b, 'speedup': 1.0, 'memory': 8192,
         'processing_power_consumption': 800.0, 'tx_energy_consumption': 5.0, 'rx_energy_consumption': 3.0},
        {'name': 'dispatcher_a', 'region': 'cloud_region_a', 'memory': 0, 'policy': 'dispatcher-policy'},
        {'name': 'dispatcher_b', 'region': 'cloud_region_b', 'memory': 0, 'policy': 'dispatcher-policy'}
    ]

    # Extend functions list if needed
    while len(functions) < n_functions:
        new_f = functions[len(functions) % len(functions)].copy()
        new_f["name"] = f"f{len(functions) + 1}"
        functions.append(new_f)

    # Trim functions list if needed
    functions = functions[:n_functions]

    # Extend class list if needed
    while len(classes) < n_classes:
        new_c = classes[len(classes) % len(classes)].copy()
        new_c["name"] = f"c{len(classes) + 1}"
        classes.append(new_c)

    # Trim classes list if needed
    classes = classes[:n_classes]

    # Randomly set specs
    for f in functions:
        f["duration_mean"] = float(rng.uniform(0.05, 0.5))
        f["init_mean"] = float(rng.uniform(0.1, 0.5))
        f["memory"] = float(rng.uniform(128, 512))
        f["duration_scv"] = float(rng.choice([1, 0.5, 0.25]))
        f["input_mean"] = float(rng.uniform(100, 5 * 1024 * 1024))

        f["speedup"] = [1.0]
        f["utility"] = [1.0]

        if variants_mode == 1:
            f["speedup"].extend(float(rng.uniform(0.25, 0.85)) for _ in range(n_variants - 1))
            f["utility"].extend(f["speedup"][1:])  # Copy randomized values to utility

    if dynamic_rate_coeff > 1.0:
        print("Forcing Poisson arrivals")
        functions_arrival_distributions = {f["name"]: "exp" for f in functions}
    else:
        functions_arrival_distributions = {f["name"]: rng.choice(["exp", "erlang", "hyper", "mmpp"]) for f in functions}

    # ** Save to a regular file instead of a temporary file **
    file_path = os.path.join(os.getcwd(), "spec_variants_"+str(seed)+".yaml")
    with open(file_path, "w") as outf:
        write_spec(outf, functions, classes, nodes, load_coeff, dynamic_rate_coeff, arrivals_to_single_node,
                   functions_arrival_distributions=functions_arrival_distributions)

    print(f"Specification saved to {file_path}")
    return file_path  # Return the file path instead of a temp file object

# Writes a spec file to outf 
def write_spec (outf, functions, classes, nodes, load_coeff=1.0, dynamic_rate_coeff=1.0, arrivals_to_single_node=True, functions_arrival_distributions=None):

    total_fun_weight = sum([f["duration_mean"]*f["memory"] for f in functions])

    def make_arrival_dict (_node, _func, _dynamic_coeff, _rate=None, _map=None):
        if _rate is not None:
            return {"node": _node, "function": _func, "rate": _rate, "dynamic_coeff": _dynamic_coeff }
        elif _map is not None:
            D0,D1=_map
            mapstr=""
            for x in np.nditer(D0):
                mapstr = mapstr + f"{x};"
            for x in np.nditer(D1):
                mapstr = mapstr + f"{x};"
            mapstr=mapstr[:-1]
            return {"node": _node, "function": _func, "map": mapstr, "dynamic_coeff": _dynamic_coeff }

    if functions_arrival_distributions is None:
        functions_arrival_distributions={}

    arrivals = []
    if arrivals_to_single_node:
        rate = 10*load_coeff
        for f in functions:
            distr = functions_arrival_distributions.get(f["name"], "exp")
            if distr == "exp":
                arv = make_arrival_dict("edge_node_a", f["name"], dynamic_rate_coeff, _rate=rate)
            else:
                if distr == "erlang":
                    D0,D1 = MAP.make_erlang2(rate)
                elif distr == "hyper":
                    D0,D1 = MAP.make_hyper(rate)
                elif distr == "mmpp":
                    D0,D1 = MAP.make_mmpp2(rate)
                else:
                    raise ValueError(f"unknow distr: {distr}")
                arv = make_arrival_dict("edge_node_a", f["name"], dynamic_rate_coeff, _map=(D0,D1))
            arrivals.append(arv)

    else:
        edge_nodes = [n for n in nodes if "edge" in n["name"]]
        rate = 10*load_coeff/len(edge_nodes)
        for f in functions:
            distr = functions_arrival_distributions.get(f["name"], "exp")
            for n in edge_nodes:
                if distr == "exp":
                    arv = make_arrival_dict(n["name"], f["name"], dynamic_rate_coeff, _rate=rate)
                else:
                    if distr == "erlang":
                        D0,D1 = MAP.make_erlang2(rate)
                    elif distr == "hyper":
                        D0,D1 = MAP.make_hyper(rate)
                    elif distr == "mmpp":
                        D0,D1 = MAP.make_mmpp2(rate)
                    else:
                        raise ValueError(f"unknow distr: {distr}")
                    arv = make_arrival_dict(n["name"], f["name"], dynamic_rate_coeff, _map=(D0,D1))
                arrivals.append(arv)

    spec = {'classes': classes, 'nodes': nodes, 'functions': functions, 'arrivals': arrivals}
    outf.write(yaml.dump(spec))
    print(yaml.dump(spec))
    outf.flush()


def write_regions_yaml(outf, regions_data):
    yaml.dump({'regions': regions_data}, outf)
    outf.flush()

def generate_regions_yaml(is_edge_green=True):
    # Determine the file name and path based on the condition
    current_directory = os.getcwd()
    if is_edge_green:
        regions_data = regions_data_green_edge
        file_name = "regions_green_edge.yml"
    else:
        regions_data = regions_data_brown_edge
        file_name = "regions_brown_edge.yml"

    file_path = os.path.join(current_directory, file_name)
    if os.path.exists(file_path):
        os.remove(file_path)
        print(f"Existing file '{file_name}' deleted.")
    with open(file_path, "w") as file:
        write_regions_yaml(file, regions_data)

    print(f"New file '{file_name}' created.")
    return file_path

regions_data_brown_edge =   [{
    "name": "cloud_region_a",
    "co2_traces_file": "co2_traces/PL_2023_hourly.csv",
    "latency_sec": {
      "cloud_region_a": 0.0001,
      "cloud_region_b": 0.0200,
      "cloud_region_c": 0.0100,
      "edge_zone_1": 0.015
    },
    "bandwidth_mbps": {
      "cloud_region_a": 10000.0,
      "cloud_region_b": 10000.0,
      "cloud_region_c": 10000.0,
      "edge_zone_1": 80.0
    },
    "neighbors": [],
    "zones": [
      {
        "name": "edge_zone_1",
        "co2_traces_file": "co2_traces/PL_2023_hourly.csv",
        "latency_sec": {
          "cloud_region_a": 0.015,
          "cloud_region_b": 0.05,
          "cloud_region_c": 0.03,
          "edge_zone_1": 0.0050
        },
        "bandwidth_mbps": {
          "cloud_region_a": 80.0,
          "cloud_region_b": 80.0,
          "cloud_region_c": 80.0,
          "edge_zone_1": 100.0
        },
        "neighbors": []
      }
    ]
  },
  {
    "name": "cloud_region_b",
    "co2_traces_file": "co2_traces/FR_2023_hourly.csv",
    "latency_sec": {
      "cloud_region_a": 0.0200,
      "cloud_region_b": 0.0001,
      "cloud_region_c": 0.0100,

    },
    "bandwidth_mbps": {
      "cloud_region_a": 10000.0,
      "cloud_region_b": 10000.0,
      "cloud_region_c": 10000.0,
      "edge_zone_1": 80.0
    },
    "neighbors": [],
    "zones": []
  },
  {
    "name": "cloud_region_c",
    "co2_traces_file": "co2_traces/IT-CNO_2023_hourly.csv",
    "latency_sec": {
      "cloud_region_a": 0.0200,
      "cloud_region_b": 0.0200,
      "cloud_region_c": 0.0001
    },
    "bandwidth_mbps": {
      "cloud_region_a": 10000.0,
      "cloud_region_b": 10000.0,
      "cloud_region_c": 10000.0,
      "edge_zone_1": 80.0
    },
    "neighbors": [],
    "zones": []
  }
]
regions_data_green_edge=  [{
    "name": "cloud_region_a",
    "co2_traces_file": "co2_traces/FR_2023_hourly.csv",
    "latency_sec": {
      "cloud_region_a": 0.0001,
      "cloud_region_b": 0.0200,
      "cloud_region_c": 0.0100,
      "edge_zone_1": 0.015
    },
    "bandwidth_mbps": {
      "cloud_region_a": 10000.0,
      "cloud_region_b": 10000.0,
      "cloud_region_c": 10000.0,
      "edge_zone_1": 80.0
    },
    "neighbors": [],
    "zones": [
      {
        "name": "edge_zone_1",
        "co2_traces_file": "co2_traces/FR_2023_hourly.csv",
        "latency_sec": {
          "cloud_region_a": 0.015,
          "cloud_region_b": 0.05,
          "cloud_region_c": 0.03,
          "edge_zone_1": 0.0050
        },
        "bandwidth_mbps": {
          "cloud_region_a": 80.0,
          "cloud_region_b": 80.0,
          "cloud_region_c": 80.0,
          "edge_zone_1": 100.0
        },
        "neighbors": []
      }
    ]
  },
  {
    "name": "cloud_region_b",
    "co2_traces_file": "co2_traces/PL_2023_hourly.csv",
    "latency_sec": {
      "cloud_region_a": 0.0200,
      "cloud_region_b": 0.0001,
      "cloud_region_c": 0.0100,

    },
    "bandwidth_mbps": {
      "cloud_region_a": 10000.0,
      "cloud_region_b": 10000.0,
      "cloud_region_c": 10000.0,
      "edge_zone_1": 80.0
    },
    "neighbors": [],
    "zones": []
  },
  {
    "name": "cloud_region_c",
    "co2_traces_file": "co2_traces/IT-CNO_2023_hourly.csv",
    "latency_sec": {
      "cloud_region_a": 0.0200,
      "cloud_region_b": 0.0200,
      "cloud_region_c": 0.0001
    },
    "bandwidth_mbps": {
      "cloud_region_a": 10000.0,
      "cloud_region_b": 10000.0,
      "cloud_region_c": 10000.0,
      "edge_zone_1": 80.0
    },
    "neighbors": [],
    "zones": []
  }
]

if __name__ == "__main__":
    with open("spec.yml", "w") as outf:
        write_spec(outf, load_coeff=4, cloud_cost=0.001)
