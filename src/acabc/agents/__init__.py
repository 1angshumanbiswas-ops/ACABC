from .audit_reports import AuditReports
from .base import Agent
from .beneficiary import BeneficiaryIntelligence
from .financial import FinancialPatternIntelligence
from .geo import GeoIntelligence
from .opportunity import EnterpriseOpportunity
from .policy import PolicyKnowledge

AGENTS = {"01": BeneficiaryIntelligence, "02": FinancialPatternIntelligence, "03": GeoIntelligence,
          "04": EnterpriseOpportunity, "05": PolicyKnowledge, "06": AuditReports}

__all__ = ["AGENTS", "Agent", "AuditReports", "BeneficiaryIntelligence", "EnterpriseOpportunity",
           "FinancialPatternIntelligence", "GeoIntelligence", "PolicyKnowledge"]
