import unittest

from phase3.patch_schema import (
    DEFAULT_PR_DESCRIPTION,
    DEFAULT_PR_TITLE,
    ModifiedFile,
    extract_patch_plan,
)


def _run(parsed):
    return {"llm": {"parsed": parsed}}


class TestPhase3PatchSchema(unittest.TestCase):
    def test_extracts_top_level_modified_files_from_one_run(self) -> None:
        plan = extract_patch_plan(
            {"runs": [_run({"modified_files": [{"file_path": "main.tf", "new_content": "abc"}]})]}
        )

        self.assertEqual(plan.modified_files, [ModifiedFile("main.tf", "abc")])

    def test_extracts_modified_files_from_multiple_runs(self) -> None:
        plan = extract_patch_plan(
            {
                "runs": [
                    _run({"modified_files": [{"file_path": "main.tf", "new_content": "ec2"}]}),
                    _run({"modified_files": [{"file_path": "modules/s3/main.tf", "new_content": "s3"}]}),
                ]
            }
        )

        self.assertEqual(
            plan.modified_files,
            [ModifiedFile("main.tf", "ec2"), ModifiedFile("modules/s3/main.tf", "s3")],
        )

    def test_ignores_invalid_modified_files(self) -> None:
        plan = extract_patch_plan(
            {
                "runs": [
                    _run(
                        {
                            "modified_files": [
                                {},
                                {"file_path": "", "new_content": "abc"},
                                {"file_path": "main.tf", "new_content": ""},
                                "not a dict",
                                {"file_path": "valid.tf", "new_content": "value"},
                            ]
                        }
                    )
                ]
            }
        )

        self.assertEqual(plan.modified_files, [ModifiedFile("valid.tf", "value")])

    def test_duplicate_file_path_uses_last_content(self) -> None:
        plan = extract_patch_plan(
            {
                "runs": [
                    _run({"modified_files": [{"file_path": "main.tf", "new_content": "old"}]}),
                    _run({"modified_files": [{"file_path": "main.tf", "new_content": "new"}]}),
                ]
            }
        )

        self.assertEqual(plan.modified_files, [ModifiedFile("main.tf", "new")])

    def test_extracts_pr_title_and_joins_descriptions(self) -> None:
        plan = extract_patch_plan(
            {
                "runs": [
                    _run({"pr_title": "Use efficient instances", "pr_description": "EC2 update."}),
                    _run({"pr_title": "Ignored later title", "pr_description": "S3 update."}),
                ]
            }
        )

        self.assertEqual(plan.pr_title, "Use efficient instances")
        self.assertEqual(plan.pr_description, "EC2 update.\n\nS3 update.")

    def test_uses_default_pr_metadata_when_missing(self) -> None:
        plan = extract_patch_plan({"runs": [_run({})]})

        self.assertEqual(plan.pr_title, DEFAULT_PR_TITLE)
        self.assertEqual(plan.pr_description, DEFAULT_PR_DESCRIPTION)

    def test_collects_nested_instances_files_with_warning(self) -> None:
        plan = extract_patch_plan(
            {
                "runs": [
                    _run(
                        {
                            "instances": {
                                "i-003": {
                                    "modified_files": [{"file_path": "main.tf", "new_content": "instance patch"}]
                                }
                            }
                        }
                    )
                ]
            }
        )

        self.assertEqual(plan.modified_files, [ModifiedFile("main.tf", "instance patch")])
        self.assertTrue(any("instances.i-003" in warning for warning in plan.warnings))

    def test_collects_nested_findings_list_files_with_warning(self) -> None:
        plan = extract_patch_plan(
            {
                "runs": [
                    _run(
                        {
                            "findings": [
                                {
                                    "modified_files": [
                                        {"file_path": "modules/s3/main.tf", "new_content": "finding patch"}
                                    ]
                                }
                            ]
                        }
                    )
                ]
            }
        )

        self.assertEqual(plan.modified_files, [ModifiedFile("modules/s3/main.tf", "finding patch")])
        self.assertTrue(any("findings[0]" in warning for warning in plan.warnings))

    def test_skips_null_parsed_and_missing_llm(self) -> None:
        plan = extract_patch_plan({"runs": [{"llm": {"parsed": None}}, {}, "invalid"]})

        self.assertEqual(plan.modified_files, [])
        self.assertEqual(plan.warnings, [])
        self.assertEqual(plan.pr_title, DEFAULT_PR_TITLE)
        self.assertEqual(plan.pr_description, DEFAULT_PR_DESCRIPTION)


if __name__ == "__main__":
    unittest.main()
