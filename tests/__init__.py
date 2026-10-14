import os
import sys

# 让测试无需安装即可导入 src 下的包
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
