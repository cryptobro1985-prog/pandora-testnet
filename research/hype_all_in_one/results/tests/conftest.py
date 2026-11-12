import sys,pickle,pytest
sys.path.insert(0,"/workspace/hype_early");sys.path.insert(0,"/workspace/pandora-testnet")
from core import DATA
import __main__,train_walkforward as _W
__main__.Norm=_W.Norm;__main__.CortexEarly=_W.CortexEarly
@pytest.fixture(scope="session")
def dataset():
    return pickle.load(open(DATA/"dataset.pkl","rb"))
@pytest.fixture(scope="session")
def tape():
    from core import Tape
    return Tape()
