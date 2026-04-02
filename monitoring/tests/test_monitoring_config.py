"""
Test suite for validating monitoring configuration files.

This module validates the structural correctness of all monitoring configuration
files including Prometheus, Alert Rules, Alertmanager, and Grafana configurations.
"""

import json
import yaml
from pathlib import Path


class TestPrometheusConfig:
    """Test Prometheus configuration file."""

    @staticmethod
    def get_prometheus_config_path():
        """Get the path to prometheus.yml relative to the project root."""
        test_dir = Path(__file__).resolve().parent
        monitoring_dir = test_dir.parent
        return monitoring_dir / "prometheus.yml"

    def test_prometheus_config_valid_yaml(self):
        """Test that prometheus.yml is valid YAML."""
        config_path = self.get_prometheus_config_path()
        assert config_path.exists(), f"prometheus.yml not found at {config_path}"

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert config is not None, "prometheus.yml is empty or invalid YAML"

    def test_prometheus_has_scrape_configs(self):
        """Test that prometheus.yml has scrape_configs section."""
        config_path = self.get_prometheus_config_path()
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert "scrape_configs" in config, "scrape_configs section missing"
        assert isinstance(config["scrape_configs"], list), "scrape_configs must be a list"

    def test_prometheus_has_all_service_jobs(self):
        """Test that all 5 service jobs are present in scrape_configs."""
        config_path = self.get_prometheus_config_path()
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        scrape_configs = config["scrape_configs"]
        job_names = [job.get("job_name") for job in scrape_configs]

        expected_services = [
            "market-data-service",
            "signal-engine",
            "execution-service",
            "risk-manager",
            "portfolio-monitor"
        ]

        for service in expected_services:
            assert service in job_names, f"Service job '{service}' not found in scrape_configs"

    def test_prometheus_has_alerting_section(self):
        """Test that prometheus.yml has alerting section pointing to alertmanager."""
        config_path = self.get_prometheus_config_path()
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert "alerting" in config, "alerting section missing"
        alerting = config["alerting"]
        assert "alertmanagers" in alerting, "alertmanagers not configured"
        assert isinstance(alerting["alertmanagers"], list), "alertmanagers must be a list"
        assert len(alerting["alertmanagers"]) > 0, "No alertmanagers configured"

    def test_prometheus_has_rule_files_section(self):
        """Test that prometheus.yml has rule_files section."""
        config_path = self.get_prometheus_config_path()
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert "rule_files" in config, "rule_files section missing"
        rule_files = config["rule_files"]
        assert isinstance(rule_files, list), "rule_files must be a list"
        assert len(rule_files) > 0, "No rule files configured"


class TestAlertRules:
    """Test Alert Rules configuration file."""

    @staticmethod
    def get_alert_rules_path():
        """Get the path to alert_rules.yml relative to the project root."""
        test_dir = Path(__file__).resolve().parent
        monitoring_dir = test_dir.parent
        return monitoring_dir / "alert_rules.yml"

    def test_alert_rules_valid_yaml(self):
        """Test that alert_rules.yml is valid YAML."""
        rules_path = self.get_alert_rules_path()
        assert rules_path.exists(), f"alert_rules.yml not found at {rules_path}"

        with open(rules_path, 'r') as f:
            rules = yaml.safe_load(f)

        assert rules is not None, "alert_rules.yml is empty or invalid YAML"

    def test_alert_rules_has_groups(self):
        """Test that alert_rules.yml has groups section."""
        rules_path = self.get_alert_rules_path()
        with open(rules_path, 'r') as f:
            rules = yaml.safe_load(f)

        assert "groups" in rules, "groups section missing"
        assert isinstance(rules["groups"], list), "groups must be a list"
        assert len(rules["groups"]) > 0, "No groups defined"

    def test_alert_rules_has_required_groups(self):
        """Test that all required group names are present."""
        rules_path = self.get_alert_rules_path()
        with open(rules_path, 'r') as f:
            rules = yaml.safe_load(f)

        groups = rules["groups"]
        group_names = [group.get("name") for group in groups]

        required_groups = [
            "circuit_breaker",
            "risk_breaches",
            "service_health",
            "execution_quality"
        ]

        for group_name in required_groups:
            assert group_name in group_names, f"Required group '{group_name}' not found"

    def test_alert_rule_has_required_fields(self):
        """Test that each alert rule has required fields."""
        rules_path = self.get_alert_rules_path()
        with open(rules_path, 'r') as f:
            rules = yaml.safe_load(f)

        for group in rules["groups"]:
            alerts = group.get("rules", [])
            for alert in alerts:
                # Check required fields
                assert "alert" in alert, f"Missing 'alert' field in rule"
                assert "expr" in alert, f"Missing 'expr' field in rule: {alert.get('alert')}"

                # Check labels section
                assert "labels" in alert, f"Missing 'labels' section in rule: {alert.get('alert')}"
                labels = alert["labels"]
                assert "severity" in labels, f"Missing 'severity' label in rule: {alert.get('alert')}"

                # Check annotations section
                assert "annotations" in alert, f"Missing 'annotations' section in rule: {alert.get('alert')}"
                annotations = alert["annotations"]
                assert "summary" in annotations, f"Missing 'summary' annotation in rule: {alert.get('alert')}"

    def test_circuit_breaker_tripped_rule_exists(self):
        """Test that CircuitBreakerTripped alert rule exists."""
        rules_path = self.get_alert_rules_path()
        with open(rules_path, 'r') as f:
            rules = yaml.safe_load(f)

        all_alert_names = []
        for group in rules["groups"]:
            alerts = group.get("rules", [])
            all_alert_names.extend([alert.get("alert") for alert in alerts])

        assert "CircuitBreakerTripped" in all_alert_names, "CircuitBreakerTripped rule not found"

    def test_drawdown_breached_rule_exists(self):
        """Test that DrawdownBreached alert rule exists."""
        rules_path = self.get_alert_rules_path()
        with open(rules_path, 'r') as f:
            rules = yaml.safe_load(f)

        all_alert_names = []
        for group in rules["groups"]:
            alerts = group.get("rules", [])
            all_alert_names.extend([alert.get("alert") for alert in alerts])

        assert "DrawdownBreached" in all_alert_names, "DrawdownBreached rule not found"

    def test_service_down_rule_exists(self):
        """Test that ServiceDown alert rule exists."""
        rules_path = self.get_alert_rules_path()
        with open(rules_path, 'r') as f:
            rules = yaml.safe_load(f)

        all_alert_names = []
        for group in rules["groups"]:
            alerts = group.get("rules", [])
            all_alert_names.extend([alert.get("alert") for alert in alerts])

        assert "ServiceDown" in all_alert_names, "ServiceDown rule not found"


class TestAlertmanagerConfig:
    """Test Alertmanager configuration file."""

    @staticmethod
    def get_alertmanager_config_path():
        """Get the path to alertmanager.yml relative to the project root."""
        test_dir = Path(__file__).resolve().parent
        monitoring_dir = test_dir.parent
        return monitoring_dir / "alertmanager.yml"

    def test_alertmanager_config_valid_yaml(self):
        """Test that alertmanager.yml is valid YAML."""
        config_path = self.get_alertmanager_config_path()
        assert config_path.exists(), f"alertmanager.yml not found at {config_path}"

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert config is not None, "alertmanager.yml is empty or invalid YAML"

    def test_alertmanager_has_route_section(self):
        """Test that alertmanager.yml has route section."""
        config_path = self.get_alertmanager_config_path()
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert "route" in config, "route section missing"
        assert config["route"] is not None, "route section is empty"

    def test_alertmanager_has_receivers_section(self):
        """Test that alertmanager.yml has receivers section."""
        config_path = self.get_alertmanager_config_path()
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert "receivers" in config, "receivers section missing"
        assert isinstance(config["receivers"], list), "receivers must be a list"
        assert len(config["receivers"]) > 0, "No receivers configured"

    def test_alertmanager_has_critical_alerts_receiver(self):
        """Test that critical-alerts receiver is configured."""
        config_path = self.get_alertmanager_config_path()
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        receivers = config["receivers"]
        receiver_names = [receiver.get("name") for receiver in receivers]

        assert "critical-alerts" in receiver_names, "critical-alerts receiver not found"

    def test_alertmanager_has_warning_alerts_receiver(self):
        """Test that warning-alerts receiver is configured."""
        config_path = self.get_alertmanager_config_path()
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        receivers = config["receivers"]
        receiver_names = [receiver.get("name") for receiver in receivers]

        assert "warning-alerts" in receiver_names, "warning-alerts receiver not found"


class TestGrafanaDashboards:
    """Test Grafana dashboard configuration files."""

    @staticmethod
    def get_trading_overview_dashboard_path():
        """Get the path to trading-overview.json dashboard."""
        test_dir = Path(__file__).resolve().parent
        monitoring_dir = test_dir.parent
        return monitoring_dir / "grafana" / "dashboards" / "trading-overview.json"

    @staticmethod
    def get_service_health_dashboard_path():
        """Get the path to service-health.json dashboard."""
        test_dir = Path(__file__).resolve().parent
        monitoring_dir = test_dir.parent
        return monitoring_dir / "grafana" / "dashboards" / "service-health.json"

    def test_trading_overview_dashboard_valid_json(self):
        """Test that trading-overview.json is valid JSON."""
        dashboard_path = self.get_trading_overview_dashboard_path()
        assert dashboard_path.exists(), f"trading-overview.json not found at {dashboard_path}"

        with open(dashboard_path, 'r') as f:
            dashboard = json.load(f)

        assert dashboard is not None, "trading-overview.json is empty or invalid JSON"

    def test_trading_overview_has_panels(self):
        """Test that trading-overview dashboard has panels array with > 0 panels."""
        dashboard_path = self.get_trading_overview_dashboard_path()
        with open(dashboard_path, 'r') as f:
            dashboard = json.load(f)

        assert "panels" in dashboard, "panels array missing"
        assert isinstance(dashboard["panels"], list), "panels must be a list"
        assert len(dashboard["panels"]) > 0, "No panels configured"

    def test_trading_overview_has_correct_title(self):
        """Test that trading-overview dashboard has title 'Trading Overview'."""
        dashboard_path = self.get_trading_overview_dashboard_path()
        with open(dashboard_path, 'r') as f:
            dashboard = json.load(f)

        assert "title" in dashboard, "title field missing"
        assert dashboard["title"] == "Trading Overview", f"Expected title 'Trading Overview', got '{dashboard['title']}'"

    def test_trading_overview_has_refresh_rate(self):
        """Test that trading-overview dashboard has refresh rate set."""
        dashboard_path = self.get_trading_overview_dashboard_path()
        with open(dashboard_path, 'r') as f:
            dashboard = json.load(f)

        assert "refresh" in dashboard, "refresh field missing"
        assert dashboard["refresh"] is not None, "refresh rate not set"

    def test_service_health_dashboard_valid_json(self):
        """Test that service-health.json is valid JSON."""
        dashboard_path = self.get_service_health_dashboard_path()
        assert dashboard_path.exists(), f"service-health.json not found at {dashboard_path}"

        with open(dashboard_path, 'r') as f:
            dashboard = json.load(f)

        assert dashboard is not None, "service-health.json is empty or invalid JSON"

    def test_service_health_has_panels(self):
        """Test that service-health dashboard has panels array with > 0 panels."""
        dashboard_path = self.get_service_health_dashboard_path()
        with open(dashboard_path, 'r') as f:
            dashboard = json.load(f)

        assert "panels" in dashboard, "panels array missing"
        assert isinstance(dashboard["panels"], list), "panels must be a list"
        assert len(dashboard["panels"]) > 0, "No panels configured"

    def test_service_health_has_correct_title(self):
        """Test that service-health dashboard has title 'Service Health'."""
        dashboard_path = self.get_service_health_dashboard_path()
        with open(dashboard_path, 'r') as f:
            dashboard = json.load(f)

        assert "title" in dashboard, "title field missing"
        assert dashboard["title"] == "Service Health", f"Expected title 'Service Health', got '{dashboard['title']}'"


class TestGrafanaProvisioning:
    """Test Grafana provisioning configuration files."""

    @staticmethod
    def get_prometheus_datasource_path():
        """Get the path to prometheus.yml datasource provisioning file."""
        test_dir = Path(__file__).resolve().parent
        monitoring_dir = test_dir.parent
        return monitoring_dir / "grafana" / "provisioning" / "datasources" / "prometheus.yml"

    @staticmethod
    def get_dashboards_provisioning_path():
        """Get the path to default.yml dashboards provisioning file."""
        test_dir = Path(__file__).resolve().parent
        monitoring_dir = test_dir.parent
        return monitoring_dir / "grafana" / "provisioning" / "dashboards" / "default.yml"

    def test_prometheus_datasource_config_valid_yaml(self):
        """Test that prometheus.yml datasource config is valid YAML."""
        config_path = self.get_prometheus_datasource_path()
        assert config_path.exists(), f"prometheus.yml datasource config not found at {config_path}"

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert config is not None, "prometheus.yml datasource config is empty or invalid YAML"

    def test_prometheus_datasource_configured(self):
        """Test that a datasource named 'Prometheus' is configured."""
        config_path = self.get_prometheus_datasource_path()
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        # Datasource config can have 'datasources' key or be a direct list
        datasources = config.get("datasources", [])
        if not datasources and isinstance(config, list):
            datasources = config

        assert isinstance(datasources, list), "datasources must be a list"
        datasource_names = [ds.get("name") for ds in datasources if isinstance(ds, dict)]

        assert "Prometheus" in datasource_names, "Prometheus datasource not found"

    def test_dashboards_provisioning_config_valid_yaml(self):
        """Test that default.yml dashboards provisioning config is valid YAML."""
        config_path = self.get_dashboards_provisioning_path()
        assert config_path.exists(), f"default.yml dashboards provisioning config not found at {config_path}"

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert config is not None, "default.yml dashboards provisioning config is empty or invalid YAML"
