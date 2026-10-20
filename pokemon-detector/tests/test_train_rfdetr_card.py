"""Validate private RF-DETR Nano training safety gates without PyTorch or GPU."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from train_rfdetr_card import (
    TrainingGateError,audit_training_dataset,train_private_card_detector,
)


class TrainingLabTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.dataset=self.root/"dataset"
        (self.dataset/"data.yaml").parent.mkdir(exist_ok=True)
        (self.dataset/"data.yaml").write_text("names: ['card','background']\n")
        for split in ("train","valid","test"):
            (self.dataset/split/"images").mkdir(parents=True)
            (self.dataset/split/"labels").mkdir()
            self.photo(split,"unique-"+split)
        self.output=self.root/"private"/"rfdetr-nano"

    def photo(self,split,bytes_content):
        path=self.dataset/split/"images"/("photo_"+split+".png")
        path.write_bytes(b"\x89PNG\r\n\x1a\n"+bytes_content.encode())
        (self.dataset/split/"labels"/("photo_"+split+".txt")).write_text(
            "0 0.5 0.5 0.5 0.5\n")
        return path

    def test_first_gate_checks_classes_and_disjoint_train_valid_test(self):
        result=audit_training_dataset(self.dataset)
        self.assertEqual(result["split_counts"],{"train":1,"valid":1,"test":1})
        self.assertFalse(result["near_duplicate_leakage_checked"])
        self.assertEqual(result["card_class_id"],0)
        self.assertFalse(result["usable_for_exact_card_identification"])

    def test_no_permission_means_no_training_and_no_output(self):
        def should_not_run():
            self.fail("Attempted loading a model before rights confirmation")
        with self.assertRaisesRegex(TrainingGateError,"permission"):
            train_private_card_detector(
                self.dataset,self.output,model_factory=should_not_run)
        self.assertFalse(self.output.exists())

    def test_missing_gpu_is_explicit_opt_in(self):
        with self.assertRaisesRegex(TrainingGateError,"CUDA unavailable"):
            train_private_card_detector(
                self.dataset,self.output,
                confirm_permission=True,cuda_available=False,
                model_factory=lambda:self.fail("Model instantiated"))
        self.assertFalse(self.output.exists())

    def test_train_opt_in_only_and_never_evaluates_test_in_script(self):
        runs=[]
        class FakeModel:
            def train(self,**kwargs):
                runs.append(kwargs)
        result=train_private_card_detector(
            self.dataset,self.output,
            confirm_permission=True,allow_cpu=True,
            cuda_available=False,model_factory=FakeModel,
            epochs=2,batch_size=1)
        self.assertEqual(len(runs),1)
        self.assertEqual(runs[0]["epochs"],2)
        self.assertEqual(runs[0]["batch_size"],1)
        self.assertEqual(runs[0]["dataset_dir"],str(self.dataset.resolve()))
        self.assertFalse(result["weights_available_and_evaluated"])
        self.assertFalse(result["test_split_evaluated_in_training_launcher"])
        self.assertTrue((self.output/"BIGSTEN_TRAINING_RUN.json").is_file())
        with self.assertRaisesRegex(TrainingGateError,"overwrite"):
            train_private_card_detector(
                self.dataset,self.output,confirm_permission=True,
                cuda_available=True,model_factory=FakeModel)

    def test_prevent_exact_train_test_leakage(self):
        original=(self.dataset/"train/images"/"photo_train.png").read_bytes()
        (self.dataset/"test/images"/"photo_test.png").write_bytes(original)
        with self.assertRaisesRegex(TrainingGateError,"leakage"):
            audit_training_dataset(self.dataset)

    def test_missing_test_is_not_a_valid_training_experiment(self):
        (self.dataset/"test/labels"/"photo_test.txt").unlink()
        with self.assertRaisesRegex(TrainingGateError,"Missing test"):
            audit_training_dataset(self.dataset)

    def test_no_checkpoint_can_be_saved_to_public_repository_root(self):
        with self.assertRaisesRegex(TrainingGateError,"private"):
            train_private_card_detector(
                self.dataset,self.root/"public-model-output",
                confirm_permission=True,cuda_available=True,
                model_factory=lambda:self.fail("Should not train"))

    def test_bad_data_yaml_no_card_class_rejected(self):
        (self.dataset/"data.yaml").write_text("names: ['book','phone']\n")
        with self.assertRaisesRegex(TrainingGateError,"card label"):
            audit_training_dataset(self.dataset)

    def test_no_unsupported_batch_settings(self):
        for kw in ({"epochs":0},{"epochs":False},{"batch_size":0},{"batch_size":17}):
            with self.subTest(kw=kw),self.assertRaises(TrainingGateError):
                train_private_card_detector(
                    self.dataset,self.output,confirm_permission=True,
                    cuda_available=True,model_factory=lambda:None,**kw)


if __name__=="__main__":
    unittest.main()
