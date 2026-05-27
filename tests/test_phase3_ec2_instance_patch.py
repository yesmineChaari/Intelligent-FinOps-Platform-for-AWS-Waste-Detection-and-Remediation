import unittest

from phase3.ec2_instance_patch import (
    apply_ec2_instance_type_updates,
    extract_ec2_module_blocks,
    scoped_terraform_for_instance,
)


MAIN_TF = """
locals {
  app1 = {
    Environment = "production"
  }
}

module "i_001" {
  source        = "./modules/ec2"
  instance_id   = "i-001"
  instance_type = "c5.xlarge"
  role          = "steady"
  common_tags   = local.app1
}

module "r_001" {
  source      = "./modules/s3"
  instance_id = "r-001"
  common_tags = local.app1
}

module "i_002" {
  source        = "./modules/ec2"
  instance_id   = "i-002"
  instance_type = "t3.large"
  tags = {
    Name = "worker"
  }
}
"""


class TestPhase3Ec2InstancePatch(unittest.TestCase):
    def test_extracts_only_ec2_modules_from_main_tf(self) -> None:
        blocks = extract_ec2_module_blocks({"main.tf": MAIN_TF})

        self.assertEqual([block.instance_id for block in blocks], ["i-001", "i-002"])
        self.assertEqual(blocks[0].instance_type, "c5.xlarge")
        self.assertEqual(blocks[1].module_name, "i_002")

    def test_scopes_current_terraform_to_matching_instance_block(self) -> None:
        block_text = scoped_terraform_for_instance({"main.tf": MAIN_TF}, "i-002")

        self.assertIsNotNone(block_text)
        self.assertIn('instance_id   = "i-002"', block_text)
        self.assertNotIn('instance_id   = "i-001"', block_text)

    def test_replaces_only_matching_instance_type(self) -> None:
        patched, changed, warnings = apply_ec2_instance_type_updates(
            {"main.tf": MAIN_TF},
            {"i-001": "c5.large"},
        )

        self.assertEqual(warnings, [])
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0].old_type, "c5.xlarge")
        self.assertEqual(changed[0].new_type, "c5.large")
        self.assertIn('instance_type = "c5.large"', patched)
        self.assertIn('instance_type = "t3.large"', patched)
        self.assertIn('source      = "./modules/s3"', patched)

    def test_warns_when_instance_is_missing(self) -> None:
        patched, changed, warnings = apply_ec2_instance_type_updates(
            {"main.tf": MAIN_TF},
            {"i-999": "t3.micro"},
        )

        self.assertEqual(patched, MAIN_TF)
        self.assertEqual(changed, [])
        self.assertEqual(warnings, ["Skipping i-999: no matching EC2 module block found in main.tf."])

    def test_warns_when_main_tf_is_missing(self) -> None:
        patched, changed, warnings = apply_ec2_instance_type_updates(
            {"modules/ec2/main.tf": MAIN_TF},
            {"i-001": "t3.micro"},
        )

        self.assertIsNone(patched)
        self.assertEqual(changed, [])
        self.assertEqual(warnings, ["No main.tf found in Terraform source; cannot patch EC2 instance types."])


if __name__ == "__main__":
    unittest.main()
