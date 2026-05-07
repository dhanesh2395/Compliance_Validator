import json
import pandas as pd
import yaml

from utils.logger import get_logger

logger = get_logger("DataLoader")


class MasterData:
    def __init__(self, base_path="data"):
        self.base_path = base_path

        self.vendor_registry = {}
        self.gst_rates = None
        self.hsn_codes = {}
        self.tds_rules = {}
        self.company_policy = {}
        self.historical = []

    def load_all(self):
        logger.info("Loading master data...")

        # Vendor registry
        with open(f"{self.base_path}/vendor_registry.json") as f:
            self.vendor_registry = json.load(f)

        # GST rates
        self.gst_rates = pd.read_csv(
            f"{self.base_path}/gst_rates_schedule.csv"
        )

        # HSN/SAC
        with open(f"{self.base_path}/hsn_sac_codes.json") as f:
            self.hsn_codes = json.load(f)

        # TDS rules
        with open(f"{self.base_path}/tds_sections.json") as f:
            self.tds_rules = json.load(f)

        # Company policy
        with open(f"{self.base_path}/company_policy.yaml") as f:
            self.company_policy = yaml.safe_load(f)

        # Historical decisions
        with open(f"{self.base_path}/historical_decisions.jsonl") as f:
            self.historical = [json.loads(line) for line in f]

        logger.info("Master data loaded successfully")

        return self