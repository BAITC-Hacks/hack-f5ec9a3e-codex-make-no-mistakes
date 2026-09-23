"""Composition root for metadata only; imports never connect to a database."""

from replenishment.calculation import models as calculation  # noqa: F401
from replenishment.catalog import models as catalog  # noqa: F401
from replenishment.demand import models as demand  # noqa: F401
from replenishment.intake import models as intake  # noqa: F401
from replenishment.inventory import models as inventory  # noqa: F401
from replenishment.kernel.db import Base
from replenishment.ordering import models as ordering  # noqa: F401
from replenishment.supply import models as supply  # noqa: F401

metadata = Base.metadata
