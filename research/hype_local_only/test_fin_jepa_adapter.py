"""Minimal Fin-JEPA causal shape, gradient and feature-contract checks."""
import unittest
try:
 import torch
 from research.hype_local_only.fin_jepa_adapter import HypeFinJEPA,validate_contract
except ImportError:
 torch=None

@unittest.skipIf(torch is None,"torch not installed")
class FinJepaTests(unittest.TestCase):
 def test_contract(self):
  self.assertEqual(len(validate_contract([f"f{i}" for i in range(116)])),116)
  with self.assertRaises(ValueError):validate_contract(["a"]*116)
 def test_forward_and_gradient(self):
  torch.manual_seed(17)
  model=HypeFinJEPA()
  x=torch.randn(3,8,116)
  y={"LOW":torch.tensor([0.,1.,0.]),"HIGH":torch.tensor([1.,0.,0.])}
  loss,out=model.supervised_loss(x,y)
  self.assertTrue(torch.isfinite(loss))
  loss.backward()
  self.assertTrue(any(p.grad is not None for p in model.parameters()))
  self.assertEqual(tuple(out["embedding"].shape),(3,64))
 def test_no_future_attention(self):
  torch.manual_seed(17)
  m=HypeFinJEPA().eval()
  x=torch.randn(2,8,116)
  y=x.clone();y[:,7,:]+=500
  with torch.no_grad():
   a=m.encode(x);b=m.encode(y)
  self.assertTrue(torch.allclose(a[:,:7],b[:,:7]))
if __name__=="__main__":unittest.main()
