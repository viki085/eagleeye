# ruff: noqa: E501 — a data file of document sentences and questions; wrapping hurts review
"""Retrieval-eval corpus: the single source of truth for the fixture documents AND the golden
questions, so every gold answer span is guaranteed to appear in its document.

Each fact is (sentence containing the span, span, paraphrased question). Questions avoid the
source wording where possible, so keyword overlap alone does not answer them. Filler text
gives every document realistic distractor content. ASCII only (PDF core fonts).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Fact:
    sentence: str
    span: str
    question: str


@dataclass(frozen=True)
class Section:
    heading: str
    facts: tuple[Fact, ...]
    filler: int = 6  # filler paragraphs after the facts (realistic length + distractors)


@dataclass(frozen=True)
class Doc:
    name: str
    kind: str  # pdf_slides | pdf_numbered | pdf_titlecase | docx | md | txt
    title: str
    sections: tuple[Section, ...]
    table: tuple[tuple[str, ...], ...] = field(default_factory=tuple)  # docx only


def F(sentence: str, span: str, question: str) -> Fact:  # noqa: N802 - short constructor
    assert span in sentence, f"span not in sentence: {span!r}"
    return Fact(sentence, span, question)


FILLER = [
    "This section is reviewed every year by the policy owner together with Legal and People "
    "Operations. Where local law sets a stricter rule, the local rule applies and the regional "
    "lead records the exception in the policy register.",
    "Managers are expected to explain these rules to new joiners during their first week and to "
    "point them to the internal portal, where the latest version of every policy is published "
    "alongside a short summary and a change history.",
    "Questions that are not answered here should be raised with the relevant service desk "
    "through the usual ticketing channel. Please include enough context for the team to act "
    "without a follow-up conversation.",
    "Exceptions are possible but must be approved in writing before the activity takes place. "
    "Retroactive approvals are only granted in genuine emergencies and are reported in the "
    "quarterly compliance review.",
    "Teams in different countries sometimes apply these rules differently in practice. The "
    "intent is always the same: be reasonable, be transparent, and ask early when in doubt "
    "rather than asking for forgiveness later.",
    "Records related to this topic are kept in the system of record named in the appendix. "
    "Copies held elsewhere, such as in personal folders or chat messages, are not considered "
    "authoritative and may be out of date.",
    "The owning team publishes a short changelog whenever this guidance changes, and important "
    "changes are announced in the monthly all-hands meeting and in the company newsletter.",
    "Where this guidance refers to amounts, they include tax unless stated otherwise. Amounts in "
    "other currencies are converted using the rate published by Finance at the start of each "
    "quarter.",
]

DOCS: tuple[Doc, ...] = (
    Doc(
        "travel_policy",
        "pdf_numbered",
        "Global Travel Policy",
        (
            Section(
                "1. Scope",
                (
                    F(
                        "The policy covers all employees, contractors and interns travelling on company "
                        "business, including trips paid by a client.",
                        "contractors and interns",
                        "Besides staff, which non-employees does the travel policy apply to?",
                    ),
                ),
            ),
            Section(
                "2. Booking",
                (
                    F(
                        "Flights must be booked through the corporate travel portal at least 14 days "
                        "before departure.",
                        "at least 14 days before departure",
                        "How far ahead do I need to reserve a plane ticket?",
                    ),
                    F(
                        "Economy class is required for flights shorter than six hours.",
                        "shorter than six hours",
                        "When is economy seating mandatory?",
                    ),
                    F(
                        "Premium economy is allowed for flights of six to ten hours.",
                        "six to ten hours",
                        "For what journey length can I upgrade to premium economy?",
                    ),
                    F(
                        "Business class needs written approval from a vice president.",
                        "approval from a vice president",
                        "Who has to sign off on a business class seat?",
                    ),
                ),
            ),
            Section(
                "3. Hotels",
                (
                    F(
                        "The nightly hotel cap is EUR 180 in EU capitals and EUR 140 elsewhere.",
                        "EUR 180 in EU capitals",
                        "What is the maximum room rate per night in places like Paris or Madrid?",
                    ),
                    F(
                        "Stays longer than five nights should use a serviced apartment.",
                        "serviced apartment",
                        "What kind of accommodation is preferred for long stays?",
                    ),
                ),
            ),
            Section(
                "4. Ground transport",
                (
                    F(
                        "Rail is preferred over flying for journeys under four hours.",
                        "journeys under four hours",
                        "When should I take the train rather than fly?",
                    ),
                    F(
                        "Car rental is limited to the compact category unless five or more people share "
                        "the car.",
                        "compact category",
                        "Which size of hire car is standard?",
                    ),
                    F(
                        "Mileage for private cars is reimbursed at EUR 0.30 per kilometre.",
                        "EUR 0.30 per kilometre",
                        "What is the reimbursement rate for driving my own car?",
                    ),
                ),
            ),
            Section(
                "5. Allowances",
                (
                    F(
                        "The daily meal allowance is EUR 55 for domestic trips and EUR 75 abroad.",
                        "EUR 75 abroad",
                        "How much food money do I get per day on an international trip?",
                    ),
                    F(
                        "Alcohol is never reimbursed, even at client dinners.",
                        "Alcohol is never reimbursed",
                        "Can I claim drinks with alcohol?",
                    ),
                ),
            ),
            Section(
                "6. Safety",
                (
                    F(
                        "Travellers to high-risk countries must register with the security desk 72 hours "
                        "before leaving.",
                        "72 hours before leaving",
                        "How early must I notify security before a trip to a dangerous destination?",
                    ),
                    F(
                        "The emergency assistance line is available 24 hours a day on +44 20 7946 0000.",
                        "+44 20 7946 0000",
                        "What number do I call for help while travelling?",
                    ),
                    F(
                        "Travel insurance is provided automatically through the corporate card.",
                        "provided automatically through the corporate card",
                        "Do I need to buy my own travel insurance?",
                    ),
                ),
            ),
        ),
    ),
    Doc(
        "security_onboarding_slides",
        "pdf_slides",
        "Security Onboarding",
        (
            Section(
                "Welcome To Security",
                (
                    F(
                        "Security training must be completed within your first 10 working days.",
                        "first 10 working days",
                        "What is the deadline for finishing the security course?",
                    ),
                    F(
                        "The course takes about 45 minutes.",
                        "about 45 minutes",
                        "How long does the onboarding security module last?",
                    ),
                ),
            ),
            Section(
                "Passwords And Access",
                (
                    F(
                        "Passwords need at least 14 characters.",
                        "at least 14 characters",
                        "What is the minimum password length?",
                    ),
                    F(
                        "Multi-factor authentication is mandatory on every account.",
                        "mandatory on every account",
                        "Is two-step login optional for any system?",
                    ),
                    F(
                        "Use the approved password manager, Keeper.",
                        "Keeper",
                        "Which password manager are we allowed to use?",
                    ),
                ),
            ),
            Section(
                "Devices",
                (
                    F(
                        "Laptops lock automatically after 5 minutes idle.",
                        "after 5 minutes idle",
                        "When does my laptop screen lock itself?",
                    ),
                    F(
                        "Full-disk encryption is enabled on every company laptop.",
                        "Full-disk encryption",
                        "How is the data on company laptops protected at rest?",
                    ),
                    F(
                        "Lost devices must be reported within 1 hour.",
                        "within 1 hour",
                        "How quickly do I need to report a missing laptop?",
                    ),
                ),
            ),
            Section(
                "Phishing",
                (
                    F(
                        "Report suspicious email with the Phish Alert button.",
                        "Phish Alert button",
                        "How do I flag a suspicious message?",
                    ),
                    F(
                        "We run a simulated phishing test every month.",
                        "every month",
                        "How often are fake phishing emails sent to staff?",
                    ),
                ),
            ),
            Section(
                "Data Handling",
                (
                    F(
                        "Customer data may only be stored in approved systems such as Salesforce.",
                        "approved systems such as Salesforce",
                        "Where am I allowed to keep client data?",
                    ),
                    F(
                        "Never send confidential files to a personal email address.",
                        "personal email address",
                        "Where must confidential documents never be forwarded?",
                    ),
                    F(
                        "USB storage devices are blocked by default.",
                        "blocked by default",
                        "Can I use a USB stick on my work machine?",
                    ),
                ),
            ),
            Section(
                "Getting Help",
                (
                    F(
                        "The security team is reachable at security@example.com.",
                        "security@example.com",
                        "How do I contact the security team by email?",
                    ),
                    F(
                        "Incidents can also be reported on the internal channel #sec-help.",
                        "#sec-help",
                        "Which chat channel is used for security problems?",
                    ),
                ),
            ),
        ),
    ),
    Doc(
        "benefits_guide",
        "pdf_titlecase",
        "Employee Benefits Guide",
        (
            Section(
                "Health Insurance",
                (
                    F(
                        "Medical cover starts on your first day of employment.",
                        "first day of employment",
                        "When does health cover begin for a new hire?",
                    ),
                    F(
                        "The company pays 80 percent of the premium for your partner and children.",
                        "80 percent of the premium",
                        "How much of family coverage does the employer fund?",
                    ),
                    F(
                        "Dental care is included up to EUR 1,500 per year.",
                        "EUR 1,500 per year",
                        "What is the annual limit for teeth treatment?",
                    ),
                ),
            ),
            Section(
                "Pension Plan",
                (
                    F(
                        "The employer matches pension contributions up to 6 percent of salary.",
                        "up to 6 percent of salary",
                        "How much retirement saving does the company match?",
                    ),
                    F(
                        "Contributions vest immediately.",
                        "vest immediately",
                        "Is there a waiting period before matched pension money is mine?",
                    ),
                ),
            ),
            Section(
                "Time Off",
                (
                    F(
                        "Full-time staff receive 28 days of paid holiday plus public holidays.",
                        "28 days of paid holiday",
                        "How much annual leave does a full-time employee get?",
                    ),
                    F(
                        "Up to 5 unused days can be carried into the next year.",
                        "Up to 5 unused days",
                        "How many vacation days roll over?",
                    ),
                    F(
                        "Parental leave is 20 weeks at full pay for every parent.",
                        "20 weeks at full pay",
                        "How long is paid leave after a baby arrives?",
                    ),
                    F(
                        "Each employee also gets 2 volunteering days a year.",
                        "2 volunteering days",
                        "How much time can I spend on charity work?",
                    ),
                ),
            ),
            Section(
                "Wellbeing",
                (
                    F(
                        "The gym subsidy is EUR 40 per month.",
                        "EUR 40 per month",
                        "How much does the company contribute to a fitness membership?",
                    ),
                    F(
                        "Free counselling is available through the Employee Assistance Programme.",
                        "Employee Assistance Programme",
                        "Where can I get confidential therapy sessions?",
                    ),
                    F(
                        "Every employee has a learning budget of EUR 1,000 per year.",
                        "learning budget of EUR 1,000",
                        "How much can I spend on courses and training?",
                    ),
                ),
            ),
            Section(
                "Other Perks",
                (
                    F(
                        "Bike-to-work leasing is offered through a salary sacrifice scheme.",
                        "salary sacrifice scheme",
                        "How is the cycle leasing paid for?",
                    ),
                    F(
                        "Home office equipment is reimbursed up to EUR 500 once.",
                        "EUR 500 once",
                        "What can I claim for setting up my desk at home?",
                    ),
                    F(
                        "Referral bonuses of EUR 2,000 are paid after the new hire passes probation.",
                        "after the new hire passes probation",
                        "When is the bonus for recommending a candidate paid out?",
                    ),
                ),
            ),
        ),
    ),
    Doc(
        "engineering_handbook",
        "docx",
        "Engineering Handbook",
        (
            Section(
                "Code Review",
                (
                    F(
                        "Every pull request needs approval from at least two reviewers.",
                        "at least two reviewers",
                        "How many approvals does a code change require?",
                    ),
                    F(
                        "Reviews should be completed within one business day.",
                        "within one business day",
                        "What is the expected turnaround for reviewing someone's change?",
                    ),
                    F(
                        "Pull requests larger than 400 lines should be split.",
                        "larger than 400 lines",
                        "At what size should a change be broken up?",
                    ),
                ),
            ),
            Section(
                "Testing",
                (
                    F(
                        "New code must keep line coverage above 80 percent.",
                        "above 80 percent",
                        "What test coverage threshold do we enforce?",
                    ),
                    F(
                        "End-to-end tests run nightly against the staging environment.",
                        "nightly against the staging environment",
                        "When and where do the full user-journey tests run?",
                    ),
                ),
            ),
            Section(
                "Deployments",
                (
                    F(
                        "Production deploys are frozen from Friday 15:00 until Monday 09:00.",
                        "Friday 15:00 until Monday 09:00",
                        "When are releases to production not allowed?",
                    ),
                    F(
                        "Every deploy uses a canary that receives 5 percent of traffic first.",
                        "5 percent of traffic",
                        "How much load does the canary get initially?",
                    ),
                    F(
                        "Rollbacks must be possible within 10 minutes.",
                        "within 10 minutes",
                        "How fast must we be able to revert a release?",
                    ),
                ),
            ),
            Section(
                "On-Call",
                (
                    F(
                        "On-call rotations last one week and hand over on Tuesdays.",
                        "hand over on Tuesdays",
                        "Which day does the pager switch to the next engineer?",
                    ),
                    F(
                        "Engineers on call receive a stipend of EUR 300 per week.",
                        "EUR 300 per week",
                        "How much extra pay comes with a week of pager duty?",
                    ),
                    F(
                        "Pages must be acknowledged within 15 minutes.",
                        "acknowledged within 15 minutes",
                        "How quickly do I have to respond to an alert?",
                    ),
                ),
            ),
            Section(
                "Architecture Decisions",
                (
                    F(
                        "Significant design choices are recorded as ADRs in the docs repository.",
                        "recorded as ADRs",
                        "Where do we document major technical decisions?",
                    ),
                    F(
                        "A new service needs sign-off from the architecture guild.",
                        "architecture guild",
                        "Who approves building a new microservice?",
                    ),
                ),
            ),
            Section(
                "Tooling",
                (
                    F(
                        "The default language for new backend services is Go.",
                        "is Go",
                        "Which programming language do we pick for fresh backend services?",
                    ),
                    F(
                        "Secrets are stored in HashiCorp Vault, never in code.",
                        "HashiCorp Vault",
                        "Where are API keys and passwords kept?",
                    ),
                ),
            ),
        ),
        table=(
            ("Environment", "Purpose", "Data"),
            ("dev", "Local development", "Synthetic"),
            ("staging", "Pre-release testing", "Anonymised copy"),
            ("prod", "Customers", "Live"),
        ),
    ),
    Doc(
        "incident_runbook",
        "md",
        "Incident Response Runbook",
        (
            Section(
                "Severity Levels",
                (
                    F(
                        "SEV1 means a full outage affecting all customers.",
                        "full outage affecting all customers",
                        "What counts as the most severe incident?",
                    ),
                    F(
                        "SEV2 covers degraded service for a subset of customers.",
                        "degraded service for a subset of customers",
                        "How is a partial slowdown for some users classified?",
                    ),
                    F(
                        "SEV3 is a minor issue with a workaround.",
                        "minor issue with a workaround",
                        "What is the lowest incident level?",
                    ),
                ),
            ),
            Section(
                "First Response",
                (
                    F(
                        "The incident commander is the first on-call engineer to acknowledge the page.",
                        "first on-call engineer to acknowledge",
                        "Who becomes the incident lead by default?",
                    ),
                    F(
                        "Open a dedicated channel named inc-YYYYMMDD-short-title.",
                        "inc-YYYYMMDD-short-title",
                        "How should the incident chat room be named?",
                    ),
                    F(
                        "Post the first status update within 15 minutes of declaring the incident.",
                        "within 15 minutes of declaring",
                        "When is the first progress note due?",
                    ),
                ),
            ),
            Section(
                "Communication",
                (
                    F(
                        "Customer-facing updates are published on status.example.com every 30 minutes.",
                        "every 30 minutes",
                        "How often do we update the public status page?",
                    ),
                    F(
                        "Only the communications lead may talk to the press.",
                        "communications lead",
                        "Who is allowed to speak to journalists during an outage?",
                    ),
                    F(
                        "Executives are paged for every SEV1 incident.",
                        "paged for every SEV1",
                        "When are senior leaders alerted?",
                    ),
                ),
            ),
            Section(
                "Recovery",
                (
                    F(
                        "Prefer a rollback over a hotfix when the cause is a recent deploy.",
                        "rollback over a hotfix",
                        "What is the preferred fix when a release broke things?",
                    ),
                    F(
                        "Database restores are run from snapshots taken every 4 hours.",
                        "every 4 hours",
                        "How frequent are the backups we restore from?",
                    ),
                ),
            ),
            Section(
                "After The Incident",
                (
                    F(
                        "A blameless postmortem is due within 5 business days.",
                        "within 5 business days",
                        "When must the incident review document be finished?",
                    ),
                    F(
                        "Action items are tracked in the INC Jira project.",
                        "INC Jira project",
                        "Where are follow-up tasks from outages recorded?",
                    ),
                    F(
                        "Postmortems are reviewed in the Thursday reliability meeting.",
                        "Thursday reliability meeting",
                        "Which meeting discusses incident write-ups?",
                    ),
                    F(
                        "Repeat incidents within 30 days are escalated to the CTO.",
                        "escalated to the CTO",
                        "What happens if the same failure recurs within a month?",
                    ),
                ),
            ),
        ),
    ),
    Doc(
        "expense_faq",
        "txt",
        "Expenses FAQ",
        (
            Section(
                "Submitting Claims",
                (
                    F(
                        "Claims must be submitted within 60 days of the purchase.",
                        "within 60 days of the purchase",
                        "What is the time limit for filing an expense?",
                    ),
                    F(
                        "Receipts are required for any item over EUR 25.",
                        "over EUR 25",
                        "Above what amount do I need proof of purchase?",
                    ),
                    F(
                        "Upload receipts in the Concur mobile app.",
                        "Concur mobile app",
                        "Which tool do I use to send in receipts?",
                    ),
                ),
            ),
            Section(
                "Approval",
                (
                    F(
                        "Your line manager approves claims up to EUR 2,000.",
                        "up to EUR 2,000",
                        "What is the most my manager can sign off on alone?",
                    ),
                    F(
                        "Claims above EUR 2,000 also need finance director approval.",
                        "finance director approval",
                        "Who else must approve a large expense?",
                    ),
                ),
            ),
            Section(
                "Payment",
                (
                    F(
                        "Approved expenses are paid with the next monthly payroll.",
                        "next monthly payroll",
                        "When do I get reimbursed?",
                    ),
                    F(
                        "Foreign currency is converted at the rate on the day of purchase.",
                        "rate on the day of purchase",
                        "Which exchange rate is used for spending abroad?",
                    ),
                ),
            ),
            Section(
                "Corporate Card",
                (
                    F(
                        "Corporate cards have a monthly limit of EUR 5,000.",
                        "monthly limit of EUR 5,000",
                        "How much can I spend on the company card each month?",
                    ),
                    F(
                        "Personal purchases on the corporate card must be repaid within 10 days.",
                        "repaid within 10 days",
                        "What if I accidentally buy something private with it?",
                    ),
                    F(
                        "Lost cards are blocked through the card provider hotline.",
                        "card provider hotline",
                        "How do I cancel a missing company card?",
                    ),
                ),
            ),
            Section(
                "Specific Items",
                (
                    F(
                        "Client gifts are limited to EUR 50 per person.",
                        "EUR 50 per person",
                        "What is the cap on presents for customers?",
                    ),
                    F(
                        "Home internet is reimbursed at EUR 30 per month for remote employees.",
                        "EUR 30 per month for remote employees",
                        "Is my broadband at home covered if I work remotely?",
                    ),
                    F(
                        "Taxis are allowed after 21:00 or when carrying equipment.",
                        "after 21:00",
                        "When can I expense a cab?",
                    ),
                    F(
                        "Conference fees need pre-approval from your budget owner.",
                        "pre-approval from your budget owner",
                        "Who must agree before I register for a paid event?",
                    ),
                    F(
                        "Fines such as parking tickets are never reimbursed.",
                        "parking tickets",
                        "Which kinds of penalties are not refunded?",
                    ),
                ),
            ),
        ),
    ),
    Doc(
        "data_retention_policy",
        "pdf_numbered",
        "Data Retention Policy",
        (
            Section(
                "1. Purpose",
                (
                    F(
                        "Data is kept only as long as there is a legal or business need.",
                        "legal or business need",
                        "On what basis may we keep information?",
                    ),
                ),
            ),
            Section(
                "2. Retention Periods",
                (
                    F(
                        "Financial records are kept for 10 years.",
                        "kept for 10 years",
                        "How long do accounting documents have to be stored?",
                    ),
                    F(
                        "Employee files are deleted 6 years after the person leaves.",
                        "6 years after the person leaves",
                        "When are personnel records destroyed?",
                    ),
                    F(
                        "Job applications from rejected candidates are deleted after 6 months.",
                        "deleted after 6 months",
                        "How long do we hold CVs of unsuccessful applicants?",
                    ),
                    F(
                        "Customer support tickets are kept for 3 years.",
                        "kept for 3 years",
                        "What is the retention period for helpdesk cases?",
                    ),
                    F(
                        "Security logs are retained for 13 months.",
                        "13 months",
                        "How long are audit logs kept?",
                    ),
                    F(
                        "Marketing contacts who never engage are removed after 24 months.",
                        "after 24 months",
                        "When are inactive mailing-list contacts purged?",
                    ),
                ),
            ),
            Section(
                "3. Deletion",
                (
                    F(
                        "Deletion is automated where the system supports it.",
                        "automated",
                        "Is removing expired data done by hand?",
                    ),
                    F(
                        "Backups are overwritten within 90 days.",
                        "within 90 days",
                        "How long until deleted data disappears from backups?",
                    ),
                ),
            ),
            Section(
                "4. Legal Hold",
                (
                    F(
                        "A legal hold suspends all deletion for the affected records.",
                        "suspends all deletion",
                        "What does a litigation hold do to retention rules?",
                    ),
                    F(
                        "Only the General Counsel can place or lift a legal hold.",
                        "General Counsel",
                        "Who controls litigation holds?",
                    ),
                ),
            ),
            Section(
                "5. Responsibilities",
                (
                    F(
                        "Each system has a named data owner responsible for applying this policy.",
                        "named data owner",
                        "Who applies retention rules for a given application?",
                    ),
                    F(
                        "Compliance audits this policy every 12 months.",
                        "every 12 months",
                        "How often is retention compliance checked?",
                    ),
                    F(
                        "Breaches of this policy are reported to the Data Protection Officer.",
                        "Data Protection Officer",
                        "Who is told when retention rules are broken?",
                    ),
                    F(
                        "Personal data requests must be answered within 30 days.",
                        "answered within 30 days",
                        "What is the deadline for responding to a subject access request?",
                    ),
                ),
            ),
        ),
    ),
    Doc(
        "sales_playbook_slides",
        "pdf_slides",
        "Sales Playbook",
        (
            Section(
                "Our Ideal Customer",
                (
                    F(
                        "Our ideal customer has 200 to 2,000 employees.",
                        "200 to 2,000 employees",
                        "What company size do we target?",
                    ),
                    F(
                        "Priority industries are logistics, retail and healthcare.",
                        "logistics, retail and healthcare",
                        "Which sectors should reps focus on?",
                    ),
                ),
            ),
            Section(
                "Pipeline Stages",
                (
                    F(
                        "A lead becomes qualified after a discovery call confirms budget and timeline.",
                        "confirms budget and timeline",
                        "What makes a prospect qualified?",
                    ),
                    F(
                        "Opportunities with no activity for 30 days are marked stale.",
                        "no activity for 30 days",
                        "When is a deal considered stale?",
                    ),
                    F(
                        "Forecasts are submitted every Monday by 12:00.",
                        "every Monday by 12:00",
                        "When is the weekly forecast due?",
                    ),
                ),
            ),
            Section(
                "Pricing And Discounts",
                (
                    F(
                        "Reps may discount up to 10 percent without approval.",
                        "up to 10 percent",
                        "How big a price cut can a rep give on their own?",
                    ),
                    F(
                        "Discounts between 10 and 25 percent need the regional sales director.",
                        "regional sales director",
                        "Who approves a 20 percent discount?",
                    ),
                    F(
                        "Multi-year deals receive an extra 5 percent discount per additional year.",
                        "extra 5 percent discount per additional year",
                        "What incentive do longer contracts get?",
                    ),
                ),
            ),
            Section(
                "Contracts",
                (
                    F(
                        "Standard payment terms are net 30 days.",
                        "net 30 days",
                        "What are our normal invoice payment terms?",
                    ),
                    F(
                        "Non-standard legal terms are reviewed by the deal desk.",
                        "deal desk",
                        "Who reviews custom contract clauses?",
                    ),
                ),
            ),
            Section(
                "Commission",
                (
                    F(
                        "Commission is 8 percent of first-year contract value.",
                        "8 percent of first-year contract value",
                        "How is a rep's commission calculated?",
                    ),
                    F(
                        "Accelerators double the rate above 120 percent of quota.",
                        "above 120 percent of quota",
                        "When does commission rate increase?",
                    ),
                    F(
                        "Commission is paid after the customer pays the first invoice.",
                        "after the customer pays the first invoice",
                        "When do reps receive commission?",
                    ),
                ),
            ),
            Section(
                "Tools",
                (
                    F(
                        "All deals are tracked in HubSpot.",
                        "tracked in HubSpot",
                        "Which CRM holds our deals?",
                    ),
                    F(
                        "Call recordings are reviewed weekly in Gong.",
                        "reviewed weekly in Gong",
                        "Where are sales calls recorded and analysed?",
                    ),
                ),
            ),
        ),
    ),
    Doc(
        "remote_work_guide",
        "docx",
        "Remote Work Guide",
        (
            Section(
                "Eligibility",
                (
                    F(
                        "Employees can work remotely after completing a 3-month probation.",
                        "3-month probation",
                        "When can a new hire start working from home?",
                    ),
                    F(
                        "Remote work abroad is allowed for up to 30 days per year.",
                        "up to 30 days per year",
                        "How long may I work from another country?",
                    ),
                ),
            ),
            Section(
                "Core Hours",
                (
                    F(
                        "Core collaboration hours are 10:00 to 15:00 local time.",
                        "10:00 to 15:00 local time",
                        "During which hours must remote staff be available?",
                    ),
                    F(
                        "Calendars must show working hours and location.",
                        "working hours and location",
                        "What should my calendar display?",
                    ),
                ),
            ),
            Section(
                "Equipment",
                (
                    F(
                        "The company provides a laptop, a monitor and a headset.",
                        "a laptop, a monitor and a headset",
                        "Which equipment is supplied for home working?",
                    ),
                    F(
                        "Ergonomic chairs can be ordered through the facilities portal.",
                        "facilities portal",
                        "How do I request a better office chair?",
                    ),
                    F(
                        "Equipment must be returned within 14 days of leaving the company.",
                        "returned within 14 days",
                        "When must kit be given back after resignation?",
                    ),
                ),
            ),
            Section(
                "Security At Home",
                (
                    F(
                        "Always connect through the corporate VPN on public Wi-Fi.",
                        "corporate VPN",
                        "What must I use on a cafe network?",
                    ),
                    F(
                        "Printing confidential documents at home is not allowed.",
                        "Printing confidential documents",
                        "What is forbidden with a home printer?",
                    ),
                ),
            ),
            Section(
                "Meetings",
                (
                    F(
                        "Cameras are expected on for meetings with fewer than 8 people.",
                        "fewer than 8 people",
                        "When should my video be switched on?",
                    ),
                    F(
                        "Team offsites take place twice a year.",
                        "twice a year",
                        "How often do teams meet in person?",
                    ),
                    F(
                        "Travel to offsites is paid by the company.",
                        "paid by the company",
                        "Who covers the cost of travelling to an offsite?",
                    ),
                ),
            ),
            Section(
                "Wellbeing",
                (
                    F(
                        "Remote employees get a coworking allowance of EUR 150 per month.",
                        "coworking allowance of EUR 150",
                        "Is there money for a shared office space?",
                    ),
                    F(
                        "Managers hold a one-to-one at least every two weeks.",
                        "at least every two weeks",
                        "How often should I have a check-in with my manager?",
                    ),
                    F(
                        "Nobody is expected to answer messages outside working hours.",
                        "outside working hours",
                        "Do I have to reply to chats in the evening?",
                    ),
                ),
            ),
        ),
    ),
    Doc(
        "it_support_faq",
        "md",
        "IT Support FAQ",
        (
            Section(
                "Getting Help",
                (
                    F(
                        "The IT service desk is open from 07:00 to 19:00 CET on weekdays.",
                        "07:00 to 19:00 CET",
                        "When is the IT helpdesk staffed?",
                    ),
                    F(
                        "Urgent issues outside those hours go to the on-call line +44 20 7946 0999.",
                        "+44 20 7946 0999",
                        "Which number do I ring for urgent IT problems at night?",
                    ),
                    F(
                        "Tickets are logged in the ServiceNow portal.",
                        "ServiceNow portal",
                        "Where do I raise an IT request?",
                    ),
                ),
            ),
            Section(
                "Accounts",
                (
                    F(
                        "Password resets are self-service at reset.example.com.",
                        "reset.example.com",
                        "Where can I reset my password myself?",
                    ),
                    F(
                        "Accounts are disabled after 90 days without a login.",
                        "90 days without a login",
                        "When does an unused account get switched off?",
                    ),
                    F(
                        "New starters receive credentials on their first morning.",
                        "first morning",
                        "When do new employees get their login details?",
                    ),
                ),
            ),
            Section(
                "Software",
                (
                    F(
                        "Software requests are approved within 3 business days.",
                        "within 3 business days",
                        "How long does it take to get new software approved?",
                    ),
                    F(
                        "Only apps from the Company Portal may be installed.",
                        "Company Portal",
                        "Where do I get approved applications from?",
                    ),
                    F(
                        "Admin rights are granted for a maximum of 24 hours.",
                        "maximum of 24 hours",
                        "How long can I have administrator access on my laptop?",
                    ),
                ),
            ),
            Section(
                "Hardware",
                (
                    F(
                        "Laptops are replaced every 4 years.",
                        "replaced every 4 years",
                        "How often do we get a new laptop?",
                    ),
                    F(
                        "Broken screens are repaired at the IT bar on the 2nd floor.",
                        "IT bar on the 2nd floor",
                        "Where can I get a cracked display fixed?",
                    ),
                    F(
                        "Loaner laptops are available for up to 2 weeks.",
                        "up to 2 weeks",
                        "How long can I borrow a spare laptop?",
                    ),
                ),
            ),
            Section(
                "Collaboration",
                (
                    F(
                        "Video calls use Microsoft Teams by default.",
                        "Microsoft Teams",
                        "Which video conferencing tool is standard?",
                    ),
                    F(
                        "Shared drives have a quota of 1 TB per team.",
                        "1 TB per team",
                        "How much storage does a team drive have?",
                    ),
                    F(
                        "Deleted files can be restored for 30 days.",
                        "restored for 30 days",
                        "How long can I recover a file I removed?",
                    ),
                ),
            ),
        ),
    ),
)


def all_facts() -> list[tuple[Doc, Section, Fact]]:
    return [(d, s, f) for d in DOCS for s in d.sections for f in s.facts]
