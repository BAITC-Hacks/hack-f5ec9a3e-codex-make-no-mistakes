# Project context

Source: the supplied [HackAlem AI brief](sources/HackAlem%20AI_%20Автоматизация%20формирования%20заказов%20поставщикам.docx.md). This is a working summary of that Markdown document; the original PDF is also preserved in `sources/`.

## Problem and user

Elektrokomplekt LLP (ekt.kz) currently calculates warehouse replenishment manually in Excel. Infrequent calculations and one-off large orders distort ordinary demand, causing excess stock and shortages.

The primary user is a purchasing manager: select a warehouse or category, calculate replenishment, inspect recommended quantities and their explanations, adjust them, and approve the order.

## Required behavior from the brief

| Requirement | Acceptance example described by the brief |
| --- | --- |
| Calculate baseline replenishment using sales, stock, transit, categories, and growth forecast | Changing a supplied input, such as goods in transit, changes the recommendation appropriately |
| Account for seasonality and sustained demand growth | A seasonal product forecast follows its seasonal pattern rather than an all-history mean |
| Estimate lost demand during stockouts | Recorded stockouts increase estimated need compared with raw-sales-only calculations |
| Exclude one-off large orders, including concentration in a single customer | An injected one-off large sale does not materially inflate regular replenishment |
| Group recommendations by supplier and explain every row | Each proposed quantity has a brief rationale and can be viewed by supplier |

Expected output: an exportable table/dashboard containing SKU, supplier, recommended quantity, rationale, and urgency.

Expected inputs in the brief: dated sales with SKU, quantity, anonymized customer and price; stock by warehouse; stockout periods; supplier directory and lead times; and a bill of materials from 1C. The task also calls for transit quantities, categories, and growth forecasts. Availability in the actual files must be checked separately; see [DATA_GUIDE.md](DATA_GUIDE.md).

Optional features: shortage-risk prioritization, minimum order quantities and supplier terms, category trend visualization, and export/sending of orders. The brief requires responsible-employee confirmation before any supplier order is sent and anonymized customer data in calculations.

Deliverables requested by the brief: a repository and README covering calculation methodology, outlier exclusion, and launch instructions. No implementation, calculation method, or technology stack has been selected in this documentation import.

## Questions to resolve before implementation

1. What is the planning date, replenishment horizon, review frequency, and service-level target?
2. What lead times apply to each supplier, and which incoming deliveries can cover each warehouse's demand?
3. Where are current warehouse-level stock and exact stockout intervals? Monthly opening balances alone do not answer either question.
4. Can the partner provide anonymized customer IDs for detecting customer-concentrated bulk orders? The sales headers inspected contain document numbers but no customer field.
5. How should sales signs, returns, transfers, missing cells, and incomplete months be interpreted?
6. Where are the category mapping, growth forecast, and 1C bill of materials, and how should the bill of materials affect replenishment?
7. Are supplier minima minimum shipment quantities, order multiples, or both? How do purchasing and stocking units convert?
8. What export schema does the existing accounting system expect?

The brief permits realistic synthetic data for development and testing. Any synthetic or assumed inputs should be clearly identified rather than presented as partner-provided facts.
