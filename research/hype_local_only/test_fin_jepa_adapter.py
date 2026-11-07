"""Minimal Fin-JEPA causal shape, gradient and schema checks."""
import unittest
try:
 import torch
 from research.hype_local_only.fin_jepa_adapter import HypeFinJEPA,validate_scalar_schema
except ImportError:
 torch=None

@unittest.skipIf(torch is None,"torch not installed")
class FinJepaTests(unittest.TestCase):
 def test_schema(self):
  self.assertEqual(len(validate_scalar_schema([f"f{i}" for i in range(86)])),86)
  with self.assertRaises(ValueError):validate_scalar_schema(["a","a"])
 def test_forward_and_gradient(self):
  torch.manual_seed(17)
  model=HypeFinJEPA(n_features=172)
  x=torch.randn(3,5,172)
  out=model(x)
  labels=torch.tensor([0.,1.,0.])
  loss=out["latent_loss"]+torch.nn.functional.binary_cross_entropy_with_logits(out["local_logits"]["LOW"],labels)
  self.assertTrue(torch.isfinite(loss))
  loss.backward()
  self.assertTrue(any(p.grad is not None for p in model.parameters()))
  self.assertEqual(tuple(out["embedding"].shape),(3,64))
 def test_causal_encoder_shape(self):
  torch.manual_seed(17)
  m=HypeFinJEPA(n_features=20).eval()
  x=torch.randn(2,5,20)
  with torch.no_grad():out=m(x)
  self.assertEqual(tuple(out["local_logits"]["LOW"].shape),(2,))
if __name__=="__main__":unittest.main()
