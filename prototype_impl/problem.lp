\* MyProblem *\
Maximize
OBJ: 1.19288815743 PCloud_cloud_region_a_f1_critical
 + 0.359990916162 PCloud_cloud_region_a_f1_standard
 + 0.525087165428 PCloud_cloud_region_a_f2_critical
 + 0.210342214695 PCloud_cloud_region_a_f2_standard
 + 0.0784260077258 PCloud_cloud_region_a_f3_critical
 + 0.0911767232318 PCloud_cloud_region_a_f3_standard
 + 1.17392500202 PCloud_cloud_region_b_f1_critical
 + 0.359990071703 PCloud_cloud_region_b_f1_standard
 + 0.456837613112 PCloud_cloud_region_b_f2_critical
 + 0.202018117501 PCloud_cloud_region_b_f2_standard
 + 0.0241169879001 PCloud_cloud_region_b_f3_critical
 + 0.0806276245641 PCloud_cloud_region_b_f3_standard
 - 6.74666666667 PDrop_f1_critical - 1.87333333333 PDrop_f1_standard
 - 5.06 PDrop_f2_critical - 1.49866666667 PDrop_f2_standard
 - 2.024 PDrop_f3_critical - 0.749333333333 PDrop_f3_standard
 + 1.01433590969 PEdge_f1_critical + 0.359904380773 PEdge_f1_standard
 + 0.2073913285 PEdge_f2_critical + 0.157482115117 PEdge_f2_standard
 - 0.102135931321 PEdge_f3_critical + 0.0396125768046 PEdge_f3_standard
 + 1.15415929279 PExec_f1_critical + 0.359990315031 PExec_f1_standard
 + 0.352304539869 PExec_f2_critical + 0.170276147333 PExec_f2_standard
 - 0.0191888583517 PExec_f3_critical + 0.0562407242437 PExec_f3_standard
Subject To
_C1: PCloud_cloud_region_a_f1_standard + PCloud_cloud_region_b_f1_standard
 + PDrop_f1_standard + PEdge_f1_standard + PExec_f1_standard = 1
_C10: 0.04 PEdge_f1_standard - Y_f1_standard <= 0
_C11: 0.07 PExec_f1_critical - X_f1_critical <= 0
_C12: 0.08 PEdge_f1_critical - Y_f1_critical <= 0
_C13: 0.072 PExec_f2_standard - X_f2_standard <= 0
_C14: 0.088 PEdge_f2_standard - Y_f2_standard <= 0
_C15: 0.135 PExec_f2_critical - X_f2_critical <= 0
_C16: 0.165 PEdge_f2_critical - Y_f2_critical <= 0
_C17: 0.06 PExec_f3_standard - X_f3_standard <= 0
_C18: 0.072 PEdge_f3_standard - Y_f3_standard <= 0
_C19: 0.09 PExec_f3_critical - X_f3_critical <= 0
_C2: PCloud_cloud_region_a_f1_critical + PCloud_cloud_region_b_f1_critical
 + PDrop_f1_critical + PEdge_f1_critical + PExec_f1_critical = 1
_C20: 0.108 PEdge_f3_critical - Y_f3_critical <= 0
_C3: PCloud_cloud_region_a_f2_standard + PCloud_cloud_region_b_f2_standard
 + PDrop_f2_standard + PEdge_f2_standard + PExec_f2_standard = 1
_C4: PCloud_cloud_region_a_f2_critical + PCloud_cloud_region_b_f2_critical
 + PDrop_f2_critical + PEdge_f2_critical + PExec_f2_critical = 1
_C5: PCloud_cloud_region_a_f3_standard + PCloud_cloud_region_b_f3_standard
 + PDrop_f3_standard + PEdge_f3_standard + PExec_f3_standard = 1
_C6: PCloud_cloud_region_a_f3_critical + PCloud_cloud_region_b_f3_critical
 + PDrop_f3_critical + PEdge_f3_critical + PExec_f3_critical = 1
_C7: 256 X_f1_critical + 256 X_f1_standard + 1024 X_f2_critical
 + 1024 X_f2_standard + 1536 X_f3_critical + 1536 X_f3_standard <= 6963.2
_C8: 256 Y_f1_critical + 256 Y_f1_standard + 1024 Y_f2_critical
 + 1024 Y_f2_standard + 1536 Y_f3_critical + 1536 Y_f3_standard <= 16384
_C9: 0.035 PExec_f1_standard - X_f1_standard <= 0
Bounds
 PCloud_cloud_region_a_f1_critical <= 1
 PCloud_cloud_region_a_f1_standard <= 1
 PCloud_cloud_region_a_f2_critical <= 1
 PCloud_cloud_region_a_f2_standard <= 1
 PCloud_cloud_region_a_f3_critical <= 1
 PCloud_cloud_region_a_f3_standard <= 1
 PCloud_cloud_region_b_f1_critical <= 1
 PCloud_cloud_region_b_f1_standard <= 1
 PCloud_cloud_region_b_f2_critical <= 1
 PCloud_cloud_region_b_f2_standard <= 1
 PCloud_cloud_region_b_f3_critical <= 1
 PCloud_cloud_region_b_f3_standard <= 1
 PDrop_f1_critical <= 1
 PDrop_f1_standard <= 1
 PDrop_f2_critical <= 1
 PDrop_f2_standard <= 1
 PDrop_f3_critical <= 1
 PDrop_f3_standard <= 1
 PEdge_f1_critical <= 1
 PEdge_f1_standard <= 1
 PEdge_f2_critical <= 1
 PEdge_f2_standard <= 1
 PEdge_f3_critical <= 1
 PEdge_f3_standard <= 1
 PExec_f1_critical <= 1
 PExec_f1_standard <= 1
 PExec_f2_critical <= 1
 PExec_f2_standard <= 1
 PExec_f3_critical <= 1
 PExec_f3_standard <= 1
End
