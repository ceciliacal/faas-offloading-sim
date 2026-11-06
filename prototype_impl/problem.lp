\* MyProblem *\
Maximize
objUtilCost: - 1.35446715897e-05 PCloud_cloud_region_a_euler_st_standard
 - 0.000693275 PDrop_euler_st_standard
 - 2.31482484966e-05 PExec_euler_st_standard
 + 6.9238375686e-07 PExec_euler_standard
Subject To
_C1: PCloud_cloud_region_a_video_st_premium + PDrop_video_st_premium
 + PExec_video_premium + PExec_video_st_premium = 1
_C10: PExec_ml_st_standard + PExec_ml_standard <= 1
_C11: PExec_euler_premium + PExec_euler_st_premium <= 1
_C12: PExec_euler_st_standard + PExec_euler_standard <= 1
_C13: 100 X_euler_premium + 100 X_euler_st_premium + 100 X_euler_st_standard
 + 100 X_euler_standard + 1500 X_ml_premium + 1500 X_ml_st_premium
 + 1500 X_ml_st_standard + 1500 X_ml_standard + 800 X_video_premium
 + 800 X_video_st_premium + 800 X_video_st_standard + 800 X_video_standard
 <= 1024
_C14: - X_video_st_premium <= 0
_C15: - X_video_st_standard <= 0
_C16: - X_ml_st_premium <= 0
_C17: - X_ml_st_standard <= 0
_C18: - X_euler_st_premium <= 0
_C19: 0.00840655732885 PExec_euler_st_standard - X_euler_st_standard <= 0
_C2: PCloud_cloud_region_a_video_st_standard + PDrop_video_st_standard
 + PExec_video_st_standard + PExec_video_standard = 1
_C20: - X_video_premium <= 0
_C21: - X_video_standard <= 0
_C22: - X_ml_premium <= 0
_C23: - X_ml_standard <= 0
_C24: - X_euler_premium <= 0
_C25: 0.000199933494057 PExec_euler_standard - X_euler_standard <= 0
_dummy: __dummy = 0
_C26: __dummy <= 0.000277777777778
_C3: PCloud_cloud_region_a_ml_st_premium + PDrop_ml_st_premium
 + PExec_ml_premium + PExec_ml_st_premium = 1
_C4: PCloud_cloud_region_a_ml_st_standard + PDrop_ml_st_standard
 + PExec_ml_st_standard + PExec_ml_standard = 1
_C5: PCloud_cloud_region_a_euler_st_premium + PDrop_euler_st_premium
 + PExec_euler_premium + PExec_euler_st_premium = 1
_C6: PCloud_cloud_region_a_euler_st_standard + PDrop_euler_st_standard
 + PExec_euler_st_standard + PExec_euler_standard = 1
_C7: PExec_video_premium + PExec_video_st_premium <= 1
_C8: PExec_video_st_standard + PExec_video_standard <= 1
_C9: PExec_ml_premium + PExec_ml_st_premium <= 1
Bounds
 PCloud_cloud_region_a_euler_st_premium <= 1
 PCloud_cloud_region_a_euler_st_standard <= 1
 PCloud_cloud_region_a_ml_st_premium <= 1
 PCloud_cloud_region_a_ml_st_standard <= 1
 PCloud_cloud_region_a_video_st_premium <= 1
 PCloud_cloud_region_a_video_st_standard <= 1
 PDrop_euler_st_premium <= 1
 PDrop_euler_st_standard <= 1
 PDrop_ml_st_premium <= 1
 PDrop_ml_st_standard <= 1
 PDrop_video_st_premium <= 1
 PDrop_video_st_standard <= 1
 PExec_euler_premium <= 1
 PExec_euler_st_premium <= 1
 PExec_euler_st_standard <= 1
 PExec_euler_standard <= 1
 PExec_ml_premium <= 1
 PExec_ml_st_premium <= 1
 PExec_ml_st_standard <= 1
 PExec_ml_standard <= 1
 PExec_video_premium <= 1
 PExec_video_st_premium <= 1
 PExec_video_st_standard <= 1
 PExec_video_standard <= 1
 __dummy = 0
End
