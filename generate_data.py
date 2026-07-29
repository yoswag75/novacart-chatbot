import json
import os
from pathlib import Path

DATA_DIR = Path("data/raw")
DATA_DIR.mkdir(parents=True, exist_ok=True)

def write_json(filename, content, metadata):
    # Chroma requires metadata separate from content but for raw we can store metadata inside or alongside
    # To make ingestion easy, we'll embed metadata in the JSON structure
    payload = {
        "content": content,
        "metadata": metadata
    }
    with open(DATA_DIR / filename, "w") as f:
        json.dump(payload, f, indent=2)

def write_md(filename, content, metadata):
    # For Markdown, we can use YAML frontmatter for metadata
    md_content = f"---\n"
    for k, v in metadata.items():
        if v is not None:
            md_content += f"{k}: {v}\n"
    md_content += f"---\n\n{content}"
    
    with open(DATA_DIR / filename, "w") as f:
        f.write(md_content)

def main():
    print("Generating synthetic datasets...")
    
    # ---------------------------------------------------------------------------------
    # Issue 1: Hardware Defect (Supplier Quality)
    # Alice Smith -> NovaWatch Series 4 won't charge
    # ---------------------------------------------------------------------------------
    
    # Support Ticket 1
    write_md("support_ticket_001.md", 
             "My NovaWatch Series 4 won't charge anymore. I left it plugged in all night.",
             {"source_type": "support_ticket", "issue_id": "issue_1", "date": "2023-10-01", 
              "customer": "Alice Smith", "order_id": None, "supplier_id": None, "department": "support", "doc_id": "support_ticket_001.md"})
              
    # Support Ticket 2 (Duplicate Record Anomaly - typo in product name)
    write_md("support_ticket_002.md", 
             "My NvoaWatch Series 4 is not charging. Plugged in overnight, dead.",
             {"source_type": "support_ticket", "issue_id": "issue_1", "date": "2023-10-01", 
              "customer": "Alice Smith", "order_id": None, "supplier_id": None, "department": "support", "doc_id": "support_ticket_002.md"})

    # Refund Log (Missing Foreign Key Anomaly - no order_id)
    write_json("refund_log_001.json",
               {"amount": 299.99, "reason": "Defective product", "status": "approved", "customer_name": "Alice Smith"},
               {"source_type": "refund_log", "issue_id": "issue_1", "date": "2023-10-02", 
                "customer": "Alice Smith", "order_id": None, "supplier_id": None, "department": "billing", "doc_id": "refund_log_001.json"})
                
    # Order Record
    write_json("order_record_1001.json",
               {"product": "NovaWatch Series 4", "price": 299.99, "supplier": "TechNova", "status": "fulfilled"},
               {"source_type": "order_record", "issue_id": "issue_1", "date": "2023-09-15", 
                "customer": "Alice Smith", "order_id": "ORD-1001", "supplier_id": "TechNova", "department": "sales", "doc_id": "order_record_1001.json"})

    # Quality Report
    write_md("quality_report_q3.md",
             "## Q3 Supplier Quality Metrics\n\nSupplier: TechNova\nProduct: NovaWatch Series 4\nIssue: 12% failure rate in charging modules reported in recent batches. Action required.",
             {"source_type": "quality_report", "issue_id": "issue_1", "date": "2023-09-30", 
              "customer": None, "order_id": None, "supplier_id": "TechNova", "department": "quality", "doc_id": "quality_report_q3.md"})
              
    # Internal Email 1 (Conflicting Data Anomaly)
    write_md("internal_email_001.md",
             "Subject: Supplier Review\nFrom: procurement@novacart.com\n\nTechNova continues to be our most reliable supplier. We should increase order volume for Q4.",
             {"source_type": "internal_email", "issue_id": "issue_1", "date": "2023-09-01", 
              "customer": None, "order_id": None, "supplier_id": "TechNova", "department": "procurement", "doc_id": "internal_email_001.md"})

    # Internal Email 2
    write_md("internal_email_002.md",
             "Subject: TechNova Charging Module Delay\nFrom: engineering@novacart.com\n\nDue to the 12% defect rate we found in TechNova's charging modules, we are delaying their next shipment until they resolve the manufacturing defect.",
             {"source_type": "internal_email", "issue_id": "issue_1", "date": "2023-10-03", 
              "customer": None, "order_id": None, "supplier_id": "TechNova", "department": "engineering", "doc_id": "internal_email_002.md"})

    # ---------------------------------------------------------------------------------
    # Issue 2: Marketing Promotion Glitch (System Error)
    # 20% promo code wasn't applied
    # ---------------------------------------------------------------------------------
    
    # Support Ticket 1
    write_md("support_ticket_003.md", 
             "I tried to use the code FALL20 for 20% off my order, but it didn't apply and I was charged full price.",
             {"source_type": "support_ticket", "issue_id": "issue_2", "date": "2023-10-10", 
              "customer": "Bob Johnson", "order_id": "ORD-1002", "supplier_id": None, "department": "support", "doc_id": "support_ticket_003.md"})
              
    # Support Ticket 2 (Duplicate & Noise)
    write_md("support_ticket_004.md", 
             "Promo code FALL20 didn't work on my order for the NovaHeadphones.",
             {"source_type": "support_ticket", "issue_id": "issue_2", "date": "2023-10-10", 
              "customer": "Bob Johnson", "order_id": "ORD-1002", "supplier_id": None, "department": "support", "doc_id": "support_ticket_004.md"})

    # Order Record
    write_json("order_record_1002.json",
               {"product": "NovaHeadphones", "price": 100.00, "promo_code": "FALL20", "discount_applied": 0.00, "total_charged": 100.00},
               {"source_type": "order_record", "issue_id": "issue_2", "date": "2023-10-10", 
                "customer": "Bob Johnson", "order_id": "ORD-1002", "supplier_id": None, "department": "sales", "doc_id": "order_record_1002.json"})

    # Refund Log (Chronological Impossibility - refund precedes purchase)
    write_json("refund_log_002.json",
               {"amount": 20.00, "reason": "Promo code error adjustment", "status": "approved", "customer_name": "Bob Johnson"},
               {"source_type": "refund_log", "issue_id": "issue_2", "date": "2023-10-09", # Before order date
                "customer": "Bob Johnson", "order_id": "ORD-1002", "supplier_id": None, "department": "billing", "doc_id": "refund_log_002.json"})

    # Marketing Campaign
    write_json("marketing_campaign_fall.json",
               {"campaign_name": "Fall Sale", "promo_code": "FALL20", "discount_pct": 20, "start_date": "2023-10-01", "end_date": "2023-10-31"},
               {"source_type": "marketing_campaign", "issue_id": "issue_2", "date": "2023-10-01", 
                "customer": None, "order_id": None, "supplier_id": None, "department": "marketing", "doc_id": "marketing_campaign_fall.json"})

    # Internal Email (Missing Document Anomaly - references non-existent file)
    write_md("internal_email_003.md",
             "Subject: Checkout Bug on Oct 10\nFrom: engineering@novacart.com\n\nWe confirmed a bug in the checkout system on Oct 10th where FALL20 was marked as valid but didn't apply the discount to the final total. See the full report in 'Q3 Promo Post-Mortem.pdf'.",
             {"source_type": "internal_email", "issue_id": "issue_2", "date": "2023-10-11", 
              "customer": None, "order_id": None, "supplier_id": None, "department": "engineering", "doc_id": "internal_email_003.md"})

    # ---------------------------------------------------------------------------------
    # Issue 3: The "Ghost" Shipment (Logistics Bottleneck)
    # ---------------------------------------------------------------------------------
    
    # Support Ticket 1 (Sensitive Data - Credit Card)
    write_md("support_ticket_005.md", 
             "My order says Delivered but I never got it. Please refund my card ending in 4111. Full card is 4111 2222 3333 4444.",
             {"source_type": "support_ticket", "issue_id": "issue_3", "date": "2023-11-05", 
              "customer": "Charlie Davis", "order_id": "ORD-2001", "supplier_id": None, "department": "support", "doc_id": "support_ticket_005.md"})

    # Order Record (Status Mismatch)
    write_json("order_record_2001.json",
               {"product": "NovaTablet", "status": "Delivered", "tracking": "TRK-999"},
               {"source_type": "order_record", "issue_id": "issue_3", "date": "2023-11-01", 
                "customer": "Charlie Davis", "order_id": "ORD-2001", "supplier_id": None, "department": "sales", "doc_id": "order_record_2001.json"})

    # Warehouse Log (Date Format Mismatch DD/MM/YYYY)
    write_json("warehouse_log_berlin.json",
               {"tracking_id": "TRK-999", "location": "Berlin Facility", "status": "Stuck at Customs", "timestamp": "04/11/2023"},
               {"source_type": "warehouse_log", "issue_id": "issue_3", "date": "2023-11-04", 
                "customer": None, "order_id": "ORD-2001", "supplier_id": None, "department": "logistics", "doc_id": "warehouse_log_berlin.json"})

    # Support Ticket 2 (Different customer, same facility)
    write_md("support_ticket_006.md", 
             "Where is my package? Tracking shows it arrived in Berlin 3 days ago but no updates since.",
             {"source_type": "support_ticket", "issue_id": "issue_3", "date": "2023-11-05", 
              "customer": "Dana White", "order_id": "ORD-2002", "supplier_id": None, "department": "support", "doc_id": "support_ticket_006.md"})

    # Internal Email
    write_md("internal_email_004.md",
             "Subject: Berlin Customs Bottleneck\nFrom: logistics@novacart.com\n\nJust a heads up, the Berlin facility is experiencing massive delays due to a customs strike. Any packages routed through there between Nov 1 and Nov 7 are currently stuck.",
             {"source_type": "internal_email", "issue_id": "issue_3", "date": "2023-11-06", 
              "customer": None, "order_id": None, "supplier_id": None, "department": "logistics", "doc_id": "internal_email_004.md"})

    print("Generation complete.")

if __name__ == "__main__":
    main()
