import os
import re
import sys
import pickle
import argparse
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score

# Try to import XGBoost, fall back if not available
try:
    from xgboost import XGBClassifier
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False

# ==========================================
# CONFIGURATION: EDIT THESE VALUES TO TEST
# ==========================================
DEFAULT_INPUTS = {
    "category": "Refund Request",
    "subject": "Refund request",
    "priority": "High",
    "channel": "Chat",
    "product": "Microsoft Office",
    "description": "It has been 31 days since my refund was applied but I still have not received it.",
    "threshold": 0.5
}

# ==========================================
# BUSINESS RULES (deterministic overrides)
# ==========================================
# Why this exists: ML models can only learn patterns present in training
# data. None of our historical tickets encode real policy facts like
# "refunds over 30 days need a human" or "3 failed reinstalls means
# escalate" -- those are business rules, not statistical patterns. So they
# must be enforced explicitly, for every subject where such a rule exists,
# rather than hoping the model infers them from word frequencies.
#
# There are THREE independent rule types, because "can AI solve this" is
# determined by different signals depending on the subject:
#
#   1. DAY_RULES      - elapsed time vs. a policy deadline
#                        (e.g. refund window, delivery SLA, warranty period)
#   2. ATTEMPT_RULES  - number of times the customer says they already tried
#                        (e.g. "reinstalled 3 times", "restarted twice")
#   3. SEVERITY_RULES - presence of high-risk keywords that should always
#                        go to a human regardless of time/attempts
#                        (e.g. security breach, fraud, data loss, safety)
#
# A ticket can match more than one rule type. Evaluation order is:
# CONTRADICTION_RULES -> SEVERITY_RULES -> DAY_RULES -> ATTEMPT_RULES -> ML.
# Contradiction is checked first because "marked done but not actually
# done" is serious regardless of elapsed time. Severity is checked next
# because risk/safety concerns should override pure time/attempt math too.
#
# Every subject below has at least one rule type covering it, EXCEPT
# "Product compatibility" and "Product recommendation", which are pure ML
# for everything except their one contradiction-pattern case (see
# CONTRADICTION_RULES) -- there's no objective deadline, retry-count, or
# fixed limit that decides solvability for an open-ended "is X compatible"
# or "recommend me something" question, so a DAY/ATTEMPT/SEVERITY rule
# there would just be an arbitrary guess dressed up as policy. The
# day/attempt thresholds used elsewhere are reasonable industry-standard
# defaults -- replace any of them with your actual policy numbers whenever
# you have them.

DAY_RULES = [
    {
        "name": "Refund SLA",
        "trigger_categories": ["refund request", "billing inquiry"],
        "trigger_subjects": ["refund request", "payment issue"],
        "trigger_keywords": ["refund"],
        "max_days": 30,
        "reason_exceeded": "Refund has been pending more than the 30-day policy window. Escalating to a human agent.",
        "reason_within": "Refund is still within the 30-day policy window -- this is normal processing time. AI can handle this (status update / reassurance).",
    },
    {
        "name": "Cancellation SLA",
        "trigger_categories": ["cancellation request"],
        "trigger_subjects": ["cancellation request"],
        "trigger_keywords": ["cancel"],
        "max_days": 14,
        "reason_exceeded": "Cancellation request has been pending more than the 14-day policy window. Escalating to a human agent.",
        "reason_within": "Cancellation request is still within the 14-day policy window -- this is normal processing time. AI can handle this.",
    },
    {
        "name": "Delivery SLA",
        "trigger_categories": ["product inquiry"],
        "trigger_subjects": ["delivery problem"],
        "trigger_keywords": ["delivery", "shipped", "shipping", "package", "courier", "deliver"],
        "max_days": 10,
        "reason_exceeded": "Delivery has been delayed beyond the standard 10-day shipping window. Escalating to a human agent (likely lost/damaged shipment).",
        "reason_within": "Delivery delay is still within the standard 10-day shipping window -- this is normal transit time. AI can handle this (tracking/status check).",
    },
    {
        "name": "Hardware Warranty",
        "trigger_categories": ["hardware issue", "technical issue"],
        "trigger_subjects": ["hardware issue", "battery life", "peripheral compatibility"],
        "trigger_keywords": ["warranty", "broken", "defective", "stopped working", "won't turn on", "wont turn on"],
        "max_days": 365,
        "reason_exceeded": "Hardware issue is outside the standard 12-month warranty window. Escalating to a human agent for a paid-repair/replacement decision.",
        "reason_within": "Hardware issue is within the standard 12-month warranty window. AI can attempt basic troubleshooting first.",
    },
    {
        "name": "Software Update Grace Period",
        "trigger_categories": ["software bug", "technical issue"],
        "trigger_subjects": ["software bug"],
        "trigger_keywords": ["since the update", "after updating", "since update", "after the update"],
        "max_days": 60,
        "reason_exceeded": "Software issue has persisted over 60 days since an update -- likely needs deeper engineering investigation rather than standard troubleshooting.",
        "reason_within": "Software issue is recent enough for AI-guided troubleshooting steps to be attempted first.",
    },
]

# ==========================================
# CONTRADICTION_RULES
# ==========================================
# Covers a DIFFERENT failure mode than days/attempts: the system's own
# records say an action already completed successfully, but the customer
# says it did NOT actually happen for them in reality.
#   e.g. "it shows refunded successfully but money not credited"
#        "status says delivered but I never received the package"
#        "ticket says resolved but the bug still happens"
#        "shows cancelled but I'm still being charged"
# This is serious REGARDLESS of how little time has passed -- even on day
# 1 -- because it points to a backend processing failure (a stuck/failed
# transaction, a sync bug, a lost shipment marked delivered by mistake),
# not just "please wait, it's still processing." So this rule is checked
# BEFORE day-based rules: a contradiction on day 1 is worse than a plain
# "no update yet" on day 29.
#
# COVERAGE: extended from the original 4 subjects (refund, payment,
# cancellation, delivery/software/network) to all 14 rule-bearing subjects,
# plus Product compatibility (one of the two "pure ML" subjects) for the
# specific "marked/listed compatible but doesn't actually work together"
# pattern requested. Product recommendation has no completed-action status
# to contradict (there's no "done" state for a suggestion), so instead of
# forcing an artificial status/contradiction pair onto it, it gets a
# "recommendation mismatch" rule below covering the closest real analogue:
# customer says the recommended product doesn't fit the stated need. It
# is still left to ML for anything else, per your call to keep it pure ML
# otherwise.
#
# Each new rule below follows the SAME two-part structure as the original
# four: a status_pattern (what the system/support previously claimed) AND
# a contradiction_keyword (what the customer says is actually true). Both
# must be present in the same ticket for the rule to fire -- a customer
# just describing a problem, with no claimed prior resolution, should NOT
# trip this and should fall through to ATTEMPT_RULES/SEVERITY_RULES/ML
# instead, since that's a first-report, not a contradiction.
CONTRADICTION_RULES = [
    {
        "name": "Refund Marked Done But Not Received",
        "trigger_categories": ["refund request", "billing inquiry"],
        "trigger_subjects": ["refund request", "payment issue"],
        # status_patterns are regexes (not exact phrases) so they catch
        # natural variation: "refunded successful", "refund was successful",
        # "shows it as refunded", "marked the refund as completed", etc.
        "status_patterns": [
            r"refund(?:ed)?\s+(?:was\s+|is\s+)?(?:successful|completed|processed|done)",
            r"(?:shows?|says?|marked?|showing)\s+(?:as\s+|it\s+as\s+|that\s+(?:it\s+(?:is|was)\s+|the\s+refund\s+(?:is|was)\s+)?)?refund(?:ed)?",
            r"refund\s+status\s+(?:shows?|says?|is)\s+(?:successful|completed|done)",
        ],
        "contradiction_keywords": ["not credited", "not received", "didn't receive", "did not receive",
                                    "haven't received", "have not received", "no money", "not reflecting",
                                    "not showing in", "not in my account", "not in my bank", "money not",
                                    "amount not"],
        "reason": "System shows the refund as completed, but the customer reports the money was never actually received. This is a backend processing discrepancy, not a normal waiting period, and needs a human agent to investigate the transaction directly -- regardless of how many days have passed.",
    },
    {
        "name": "Delivery Marked Done But Not Received",
        "trigger_categories": ["product inquiry"],
        "trigger_subjects": ["delivery problem"],
        "status_patterns": [
            r"(?:shows?|says?|marked?|showing|tracking\s+shows?)\s+(?:as\s+|it\s+as\s+)?delivered",
            r"delivered\s+(?:successfully|already)",
        ],
        "contradiction_keywords": ["not received", "didn't receive", "did not receive", "haven't received",
                                    "have not received", "never arrived", "never got it", "no package"],
        "reason": "System shows the package as delivered, but the customer reports never receiving it. This points to a lost shipment or scanning error and needs a human agent to investigate (possible carrier claim), regardless of how recent the order is.",
    },
    {
        "name": "Cancellation Marked Done But Still Charged",
        "trigger_categories": ["cancellation request"],
        "trigger_subjects": ["cancellation request"],
        "status_patterns": [
            r"(?:shows?|says?|marked?|showing)\s+(?:as\s+|it\s+as\s+)?cancel(?:led|ed)",
            r"cancel(?:led|ed)\s+(?:successfully|confirmed)",
            r"cancellation\s+(?:confirmed|completed)",
        ],
        "contradiction_keywords": ["still being charged", "still charged", "charged again", "still billed",
                                    "money still deducted", "still active", "wasn't cancelled", "was not cancelled",
                                    "wasn't canceled", "was not canceled"],
        "reason": "System shows the cancellation as completed, but the customer reports still being charged or the subscription still active. This is a billing-system sync failure and needs a human agent, regardless of how recently it was requested.",
    },
    {
        "name": "Fix Marked Resolved But Issue Persists",
        "trigger_categories": ["technical issue", "software bug", "hardware issue"],
        "trigger_subjects": ["software bug", "hardware issue", "network problem"],
        "status_patterns": [
            r"(?:shows?|says?|marked?|showing|closed\s+as)\s+(?:as\s+)?(?:resolved|fixed)",
            r"(?:resolved|fixed)\s+(?:successfully|already)",
        ],
        "contradiction_keywords": ["still happening", "still occurs", "still crashes", "still not working",
                                    "issue persists", "same problem", "not actually fixed", "still broken"],
        "reason": "Ticket/system shows the issue as resolved, but the customer reports the same problem is still occurring. This means the prior fix didn't actually work and needs a human agent to re-investigate, rather than re-running the same automated steps.",
    },
    {
        "name": "Hardware Marked Repaired/Replaced But Still Faulty",
        "trigger_categories": ["hardware issue", "technical issue"],
        "trigger_subjects": ["hardware issue"],
        "status_patterns": [
            r"(?:shows?|says?|marked?|showing)\s+(?:that\s+)?(?:the\s+)?(?:device|hardware|item)?\s*(?:as\s+|was\s+|is\s+)?(?:repaired|replaced|fixed)",
            r"(?:repaired|replaced)\s+(?:successfully|already|under warranty)",
            r"(?:replacement|repair)\s+(?:was\s+)?(?:sent|completed|processed)",
        ],
        "contradiction_keywords": ["still broken", "still doesn't work", "still does not work", "still defective",
                                    "same issue", "still not working", "never got the replacement",
                                    "didn't receive the replacement", "did not receive the replacement"],
        "reason": "Records show a hardware repair or replacement was completed, but the customer reports the device is still faulty or the replacement never arrived. This is a fulfillment or repair-quality failure and needs a human agent to investigate, regardless of how recently the repair was logged.",
    },
    {
        "name": "Battery Marked Fixed But Still Draining",
        "trigger_categories": ["hardware issue", "technical issue"],
        "trigger_subjects": ["battery life"],
        "status_patterns": [
            r"(?:shows?|says?|marked?|showing)\s+(?:that\s+)?(?:the\s+)?(?:battery|issue)?\s*(?:as\s+|was\s+|is\s+)?(?:resolved|fixed|replaced)",
            r"battery\s+(?:was\s+)?(?:replaced|recalibrated)",
            r"(?:calibration|recalibration)\s+(?:was\s+)?(?:completed|successful)",
        ],
        "contradiction_keywords": ["still drains", "still draining", "still dies fast", "still loses charge",
                                    "still doesn't last", "still does not last", "same battery problem",
                                    "no improvement"],
        "reason": "Support records show a battery fix, replacement, or recalibration was completed, but the customer reports the same drain problem continues. This means the prior fix didn't resolve the underlying issue and needs a human agent rather than another round of the same steps.",
    },
    {
        "name": "Peripheral Marked Compatible But Won't Pair",
        "trigger_categories": ["hardware issue", "technical issue"],
        "trigger_subjects": ["peripheral compatibility"],
        "status_patterns": [
            r"(?:shows?|says?|marked?|listed?|listing)\s+(?:as\s+|it\s+as\s+)?compat(?:ible|ibility)",
            r"compat(?:ible|ibility)\s+(?:confirmed|verified)",
        ],
        "contradiction_keywords": ["won't pair", "wont pair", "doesn't pair", "does not pair", "won't connect",
                                    "wont connect", "doesn't connect", "does not connect", "not actually compatible",
                                    "not detected", "not recognized"],
        "reason": "The product or support page lists the peripheral as compatible, but the customer reports it doesn't actually pair or connect with their device. This is a real compatibility/firmware discrepancy, not user error, and needs a human agent to verify, regardless of how the listing reads.",
    },
    {
        "name": "Software Marked Compatible But Won't Pair/Sync",
        "trigger_categories": ["hardware issue", "technical issue"],
        "trigger_subjects": ["product compatibility"],
        "status_patterns": [
            r"(?:shows?|says?|marked?|listed?|listing)\s+(?:as\s+|it\s+as\s+)?compat(?:ible|ibility)",
            r"compat(?:ible|ibility)\s+(?:confirmed|verified)",
        ],
        "contradiction_keywords": ["won't pair", "wont pair", "doesn't pair", "does not pair", "won't connect",
                                    "wont connect", "doesn't connect", "does not connect", "not actually compatible",
                                    "not detected", "not recognized", "doesn't actually work with",
                                    "does not actually work with", "doesn't work with", "does not work with",
                                    "won't sync", "wont sync", "doesn't sync", "does not sync"],
        "reason": "The listing or support documentation says the product/device is compatible, but the customer reports it doesn't actually work, pair, or sync with what they have. This is a real compatibility discrepancy, not user error, and needs a human agent to verify -- this is the only situation in which 'Product compatibility' is taken out of pure ML, since every other compatibility question here has no real status to contradict.",
    },
    {
        "name": "Account Marked Restored But Still Locked Out",
        "trigger_categories": ["account access", "billing inquiry", "technical issue"],
        "trigger_subjects": ["account access"],
        "status_patterns": [
            r"(?:shows?|says?|marked?|showing)\s+(?:that\s+)?(?:my\s+|the\s+)?(?:account|access|password)?\s*(?:as\s+|was\s+|is\s+|has\s+been\s+)?(?:restored|unlocked|reset|recovered)",
            r"(?:password|access)\s+(?:was\s+)?(?:reset|restored)\s+(?:successfully|already)",
            r"account\s+(?:has\s+been\s+)?(?:unlocked|restored|recovered)",
        ],
        "contradiction_keywords": ["still locked", "still can't log in", "still cannot log in", "still can't access",
                                    "still cannot access", "still says invalid", "still getting locked out",
                                    "didn't work", "did not work"],
        "reason": "System or support says the account was unlocked, reset, or restored, but the customer reports they still can't get in. This points to a sync failure between the support tooling and the live account system and needs a human agent, regardless of how recently the reset was logged.",
    },
    {
        "name": "Data Marked Recovered But Still Missing",
        "trigger_categories": ["technical issue"],
        "trigger_subjects": ["data loss"],
        "status_patterns": [
            r"(?:shows?|says?|marked?|showing)\s+(?:that\s+)?(?:the\s+)?(?:data|files?|recovery|restoration)?\s*(?:as\s+|was\s+|were\s+|is\s+)?(?:recovered|restored|completed|successful)",
            r"(?:recovery|restoration)\s+(?:was\s+)?(?:completed|successful)",
            r"(?:files?|data)\s+(?:were|was)\s+(?:recovered|restored)",
        ],
        "contradiction_keywords": ["still missing", "still gone", "still can't find", "still cannot find",
                                    "didn't come back", "did not come back", "not actually there", "still lost",
                                    "files are empty", "folder is empty"],
        "reason": "Support records show the data recovery as completed, but the customer reports the files are still missing. This needs a human agent to investigate the recovery process directly rather than reattempting the same automated recovery, regardless of how soon after the 'completed' status this is reported.",
    },
    {
        "name": "Installation Marked Complete But App Won't Open",
        "trigger_categories": ["technical issue", "product setup"],
        "trigger_subjects": ["installation support"],
        "status_patterns": [
            r"(?:shows?|says?|marked?|showing)\s+(?:as\s+)?(?:installed|complete|successful)",
            r"install(?:ation|ed)?\s+(?:was\s+)?(?:successful|completed|finished)",
        ],
        "contradiction_keywords": ["won't open", "wont open", "doesn't open", "does not open", "won't launch",
                                    "wont launch", "doesn't launch", "does not launch", "won't start",
                                    "wont start", "doesn't start", "does not start", "crashes on open",
                                    "crashes on launch", "crashes on startup"],
        "reason": "Installation is marked as successful or complete, but the customer reports the app still won't actually open or launch. This points to a corrupted install or a packaging/dependency problem, not a normal post-install hiccup, and needs a human agent rather than another guided reinstall.",
    },
    {
        "name": "Setup Marked Complete But Device Not Working",
        "trigger_categories": ["product inquiry", "product setup", "technical issue"],
        "trigger_subjects": ["product setup"],
        "status_patterns": [
            r"(?:shows?|says?|marked?|showing)\s+(?:that\s+)?(?:the\s+)?(?:setup|device)?\s*(?:as\s+|was\s+|is\s+)?(?:set\s*up|configured|complete)",
            r"set\s*up\s+(?:was\s+)?(?:successful|completed|finished)",
            r"setup\s+(?:wizard\s+)?(?:says?|confirmed)\s+(?:it'?s\s+)?(?:done|complete)",
        ],
        "contradiction_keywords": ["still doesn't work", "still does not work", "won't turn on", "wont turn on",
                                    "won't connect to", "wont connect to", "still not working", "doesn't do anything",
                                    "does not do anything", "stuck on setup", "stuck at setup"],
        "reason": "Setup is marked as complete or successful, but the customer reports the device still doesn't actually work. This suggests the setup process itself failed silently and needs a human agent to walk through it directly rather than repeating the same automated wizard.",
    },
    {
        "name": "Display Marked Fixed But Visual Issue Persists",
        "trigger_categories": ["hardware issue", "technical issue"],
        "trigger_subjects": ["display issue"],
        "status_patterns": [
            r"(?:shows?|says?|marked?|showing)\s+(?:that\s+)?(?:the\s+)?(?:screen|display)?\s*(?:as\s+|was\s+|is\s+)?(?:resolved|fixed|replaced|repaired)",
            r"(?:screen|display)\s+(?:was\s+)?(?:replaced|repaired)\s+(?:successfully|already)",
        ],
        "contradiction_keywords": ["still flickering", "still flickers", "still distorted", "still has lines",
                                    "still lines on", "lines are still", "still discolored", "still discoloured",
                                    "still cracked", "same display issue", "still glitching", "still glitches"],
        "reason": "Support records show the display issue as resolved or the screen as replaced, but the customer reports the same visual problem continues. This means the prior fix didn't actually work and needs a human agent to re-investigate rather than re-running the same automated checks.",
    },
    {
        "name": "Recommendation Doesn't Match Stated Need",
        "trigger_categories": ["product inquiry"],
        "trigger_subjects": ["product recommendation"],
        # No completed-action "status" exists for a recommendation, so the
        # first half of this rule checks for a PRIOR recommendation having
        # been given (by support or by this same system) rather than a
        # status claim -- the closest real analogue to "system says X."
        "status_patterns": [
            r"(?:you\s+)?recommend(?:ed)?\s+(?:me\s+)?(?:this|that|the)",
            r"(?:suggested|recommended)\s+(?:this|that|it)\s+(?:to\s+me)?",
        ],
        "contradiction_keywords": ["doesn't do what i need", "does not do what i need", "doesn't fit my needs",
                                    "does not fit my needs", "isn't compatible with", "is not compatible with",
                                    "doesn't have the feature", "does not have the feature", "wrong recommendation",
                                    "not what i asked for", "not what i needed"],
        "reason": "Customer says a specific product was already recommended to them, but it doesn't actually meet the need they described. This means the earlier recommendation was a mismatch and needs a human agent to reassess requirements directly, rather than generating another automated suggestion from the same inputs.",
    },
]

ATTEMPT_RULES = [
    {
        "name": "Repeated Self-Fix Attempts",
        "trigger_categories": ["technical issue", "software bug", "hardware issue", "network problem", "account access"],
        "trigger_subjects": ["software bug", "hardware issue", "network problem", "account access",
                             "installation support", "product setup", "peripheral compatibility",
                             "display issue", "data loss", "battery life"],
        "trigger_keywords": ["tried", "attempt", "reinstall", "restart", "reset", "retried", "re-tried"],
        "max_attempts": 2,
        "reason_exceeded": "Customer has already attempted standard troubleshooting multiple times without success. Escalating to a human agent rather than repeating the same automated steps.",
        "reason_within": "Customer has tried few or no troubleshooting steps yet. AI can guide them through standard steps first.",
    },
]

SEVERITY_RULES = [
    {
        "name": "Security / Account Compromise",
        "trigger_categories": ["account access", "billing inquiry", "technical issue"],
        "trigger_subjects": ["account access", "payment issue"],
        "trigger_keywords": ["hacked", "unauthorized", "fraud", "fraudulent", "stolen", "breach",
                              "someone accessed", "suspicious login", "identity theft"],
        "reason": "Possible account compromise or fraud. Escalating directly to a human agent for security review rather than automated handling.",
    },
    {
        "name": "Data Loss - Irreversible Risk",
        "trigger_categories": ["technical issue"],
        "trigger_subjects": ["data loss"],
        "trigger_keywords": ["lost all", "permanently deleted", "no backup", "everything is gone", "lost my data", "lost everything"],
        "reason": "Potential irreversible data loss reported. Escalating to a human agent rather than risking further data damage with automated steps.",
    },
    {
        "name": "Payment / Billing Dispute Risk",
        "trigger_categories": ["billing inquiry"],
        "trigger_subjects": ["payment issue"],
        "trigger_keywords": ["double charged", "charged twice", "unauthorized charge", "wrong amount charged", "overcharged"],
        "reason": "Billing discrepancy involving an incorrect charge. Escalating to a human agent since this needs account-level financial correction.",
    },
    {
        "name": "Safety Hazard",
        "trigger_categories": ["hardware issue", "technical issue"],
        "trigger_subjects": ["hardware issue", "battery life"],
        "trigger_keywords": ["smoke", "burning smell", "caught fire", "sparking", "overheating badly", "explod"],
        "reason": "Potential physical safety hazard reported (heat/fire/smoke). Escalating immediately to a human agent; this is not a chatbot-safe situation.",
    },
]

# Mapping Category Dropdown to Ticket Type in the CSV
CATEGORY_TO_TICKET_TYPE = {
    'technical issue': 'Technical issue',
    'billing inquiry': 'Billing inquiry',
    'product inquiry': 'Product inquiry',
    'refund request': 'Refund request',
    'cancellation request': 'Cancellation request',
    'product setup': 'Product inquiry',
    'hardware issue': 'Technical issue',
    'software bug': 'Technical issue',
    'network problem': 'Technical issue',
    'account access': 'Billing inquiry',
    'other (specify below)': 'Technical issue'
}

# Allowed values in the dataset for verification and fallback mapping
ALLOWED_PRIORITIES = ['Low', 'Medium', 'High', 'Critical']
ALLOWED_CHANNELS = ['Phone', 'Email', 'Social media', 'Chat']
ALLOWED_SUBJECTS = [
    'Account access', 'Battery life', 'Cancellation request', 'Data loss',
    'Delivery problem', 'Display issue', 'Hardware issue', 'Installation support',
    'Network problem', 'Payment issue', 'Peripheral compatibility',
    'Product compatibility', 'Product recommendation', 'Product setup',
    'Refund request', 'Software bug'
]
ALLOWED_PRODUCTS = [
    'Adobe Photoshop', 'Amazon Echo', 'Amazon Kindle', 'Apple AirPods', 'Asus ROG',
    'Autodesk AutoCAD', 'Bose QuietComfort', 'Bose SoundLink Speaker', 'Canon DSLR Camera',
    'Canon EOS', 'Dell XPS', 'Dyson Vacuum Cleaner', 'Fitbit Charge', 'Fitbit Versa Smartwatch',
    'Garmin Forerunner', 'GoPro Action Camera', 'GoPro Hero', 'Google Nest', 'Google Pixel',
    'HP Pavilion', 'LG OLED', 'LG Smart TV', 'LG Washing Machine', 'Lenovo ThinkPad',
    'MacBook Pro', 'Microsoft Office', 'Microsoft Surface', 'Microsoft Xbox Controller',
    'Nest Thermostat', 'Nikon D', 'Nintendo Switch', 'Nintendo Switch Pro Controller',
    'Philips Hue Lights', 'PlayStation', 'Roomba Robot Vacuum', 'Samsung Galaxy',
    'Samsung Soundbar', 'Sony 4K HDR TV', 'Sony PlayStation', 'Sony Xperia', 'Xbox', 'iPhone'
]


def find_closest_match(value, allowed_values, default):
    """Finds the closest matching string in allowed_values to avoid OHE unseen value issues."""
    if not isinstance(value, str):
        return default
    val_clean = value.strip().lower()

    for allowed in allowed_values:
        if allowed.lower().strip() == val_clean:
            return allowed

    for allowed in allowed_values:
        if allowed.lower().strip() in val_clean or val_clean in allowed.lower().strip():
            return allowed

    return default


def map_inputs(category, subject, priority, channel, product, description):
    """Maps user inputs to the exact casing and fields expected by the dataset model."""
    cat_clean = str(category).strip().lower()
    ticket_type = CATEGORY_TO_TICKET_TYPE.get(cat_clean, "Technical issue")

    ticket_subject = find_closest_match(subject, ALLOWED_SUBJECTS, "Software bug")
    ticket_priority = find_closest_match(priority, ALLOWED_PRIORITIES, "Medium")
    ticket_channel = find_closest_match(channel, ALLOWED_CHANNELS, "Email")
    product_purchased = find_closest_match(product, ALLOWED_PRODUCTS, "Microsoft Office")
    ticket_description = str(description).strip() if description else "No description provided."

    return {
        "Product Purchased": product_purchased,
        "Ticket Type": ticket_type,
        "Ticket Subject": ticket_subject,
        "Ticket Priority": ticket_priority,
        "Ticket Channel": ticket_channel,
        "Ticket Description": ticket_description,
        "_category_raw": cat_clean,
    }


# ==========================================
# DAY/DATE PARSING FOR RULE ENGINE
# ==========================================
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
    "couple": 2, "few": 3, "several": 5,
}

_MONTH_NAMES = (
    "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    "aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)


def _word_to_number(word):
    word = word.strip().lower()
    if word.isdigit():
        return int(word)
    return _NUMBER_WORDS.get(word)


def extract_elapsed_days(description, reference_date=None):
    """
    Attempts to extract a number of elapsed days from free-text description.
    Looks for patterns like:
      - "31 days", "two weeks", "1 month"
      - "since 31 days", "for the past 5 days"
      - "applied on 2026-05-10" / "on May 10th" (computes days from that date)
    Returns the MAXIMUM elapsed-day figure found (the most conservative /
    serious interpretation), or None if nothing could be parsed.
    """
    if not isinstance(description, str) or not description.strip():
        return None

    if reference_date is None:
        reference_date = datetime.now()

    text = description.lower()
    candidates = []

    # Pattern 1: "<number> day(s)/week(s)/month(s)/year(s)"
    unit_multiplier = {
        "day": 1, "days": 1, "week": 7, "weeks": 7,
        "month": 30, "months": 30, "year": 365, "years": 365,
    }
    pattern_num_unit = re.compile(
        r"\b(\d{1,4}|" + "|".join(_NUMBER_WORDS.keys()) + r")\s*(day|days|week|weeks|month|months|year|years)\b"
    )
    for match in pattern_num_unit.finditer(text):
        num = _word_to_number(match.group(1))
        unit = match.group(2)
        if num is not None:
            candidates.append(num * unit_multiplier[unit])

    # Pattern 2: explicit date mentions e.g. "on 2026-05-10", "on May 10, 2026", "on May 10th"
    date_patterns = [
        r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b",                     # 2026-05-10
        r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b",                      # 05/10/2026
        rf"\b({_MONTH_NAMES})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s*(\d{{4}})?\b",  # May 10th, 2026
    ]
    for pat in date_patterns:
        for match in re.finditer(pat, text):
            try:
                groups = match.groups()
                if groups[0].isdigit() and len(groups[0]) == 4:
                    year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                elif groups[0].isdigit():
                    month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
                else:
                    month_str = groups[0][:3]
                    month_lookup = {
                        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
                    }
                    month = month_lookup.get(month_str)
                    day = int(groups[1])
                    year = int(groups[2]) if groups[2] else reference_date.year
                    if month is None:
                        continue
                parsed_date = datetime(year, month, day)
                if parsed_date <= reference_date:
                    candidates.append((reference_date - parsed_date).days)
            except (ValueError, IndexError):
                continue

    if not candidates:
        return None

    return max(candidates)


_ORDINAL_WORDS = {
    "twice": 2, "thrice": 3, "once": 1,
}


def extract_attempt_count(description):
    """
    Attempts to extract how many times the customer says they already
    tried to fix the issue themselves, e.g.:
      - "I've tried restarting it 3 times"
      - "reinstalled it twice"
      - "tried multiple times" / "tried several times" (defaults to 3)
      - "tried again and again" (defaults to 3)
    Returns the MAXIMUM attempt count found, or None if nothing matched.
    Note: a bare single mention of "tried" / "reinstalled" with no
    explicit count is treated as 1 attempt, not ignored, so a customer who
    says "I tried restarting but it didn't work" still registers as
    1 attempt for the ATTEMPT_RULES threshold check.
    """
    if not isinstance(description, str) or not description.strip():
        return None

    text = description.lower()
    candidates = []

    attempt_verbs = r"(?:tried|attempt(?:ed|s)?|reinstall(?:ed|ing)?|restart(?:ed|ing)?|reset|re-?tried)"

    # "<verb> ... <number> times"
    pattern_explicit = re.compile(
        attempt_verbs + r"[^.]{0,30}?\b(\d{1,2}|" + "|".join(_NUMBER_WORDS.keys()) + r")\s*times\b"
    )
    for match in pattern_explicit.finditer(text):
        num = _word_to_number(match.group(1))
        if num is not None:
            candidates.append(num)

    # "<verb> ... twice / thrice"
    pattern_word_num = re.compile(attempt_verbs + r"[^.]{0,20}?\b(twice|thrice|once)\b")
    for match in pattern_word_num.finditer(text):
        candidates.append(_ORDINAL_WORDS[match.group(1)])

    # Vague-but-repeated phrasing: "multiple times", "several times", "many times",
    # "again and again", "over and over" -- treat as 3 (clearly more than once,
    # exact count unknown, so use the rule's threshold-crossing default)
    vague_repeat = re.compile(
        attempt_verbs + r"[^.]{0,30}?\b(multiple times|several times|many times|repeatedly)\b"
        r"|\b(again and again|over and over)\b"
    )
    if vague_repeat.search(text):
        candidates.append(3)

    # Bare mention of an attempt verb with no explicit count -> count as 1
    if not candidates and re.search(attempt_verbs, text):
        candidates.append(1)

    if not candidates:
        return None

    return max(candidates)


def _keyword_in_text(keywords, text):
    return any(kw in text for kw in keywords)


# Contradiction keyword phrases are short negation patterns ("doesn't work
# with", "still can't log in") where real customer phrasing commonly
# inserts an extra adverb in the middle ("doesn't ACTUALLY work with",
# "still REALLY can't log in"). A plain substring check would miss those.
# This converts each keyword phrase's internal spaces into a small regex
# gap that optionally allows one such word, without turning the whole
# phrase into an open-ended fuzzy match (still requires every other word
# in the phrase, in order, so it can't drift into unrelated matches).
_INTERVENING_WORDS = r"(?:\s+(?:actually|really|literally|even|still|just))?"


def _contradiction_keyword_in_text(keywords, text):
    for kw in keywords:
        if kw in text:
            return True
        pattern = _INTERVENING_WORDS.join(re.escape(word) for word in kw.split(" "))
        if re.search(pattern, text):
            return True
    return False


def _rule_matches(rule, cat_lower, subject_lower, desc_lower, keyword_field="trigger_keywords"):
    """Shared matching logic: category match OR subject match, AND keyword match."""
    category_match = cat_lower in rule.get("trigger_categories", [])
    subject_match = subject_lower in rule.get("trigger_subjects", [])
    keyword_match = _keyword_in_text(rule.get(keyword_field, []), desc_lower)
    # Require keyword match ALWAYS (keywords define the actual topic of the
    # rule), plus at least a category or subject match so we don't fire a
    # refund rule just because the word "refund" appears in passing on an
    # unrelated technical ticket.
    return keyword_match and (category_match or subject_match)


def evaluate_business_rules(category_raw, ticket_type, ticket_subject, description, reference_date=None):
    """
    Checks the description against, in priority order:
      1. CONTRADICTION_RULES - "system says done, customer says not done"
      2. SEVERITY_RULES       - safety/security/fraud/irreversible risk
      3. DAY_RULES            - elapsed time vs. a policy deadline
      4. ATTEMPT_RULES        - number of self-fix attempts already tried

    Contradiction is checked FIRST because a "marked done but not actually
    done" report is serious regardless of how little time has passed --
    even on day 1 it indicates a backend failure, which is worse than a
    plain "still waiting" report on day 29. Severity/safety is checked
    next because risk should override pure time/attempt math too.

    For DAY_RULES and ATTEMPT_RULES, being WITHIN the policy window now
    forces a decisive "yes" (AI can help) rather than leaving it for the
    ML model to guess -- a ticket that's just normal, on-time waiting is
    not an ambiguous case, so there's no reason to gamble on a probability.

    Returns a dict describing the outcome of the FIRST matching rule, or
    None if nothing matched at all (pure ML fallback).

    Returned dict shape:
      {
        "triggered": bool,       # True = a hard override decision was made
        "decision": "yes"/"no",
        "reason": str,
        "rule_name": str,
        "rule_type": "contradiction"/"severity"/"day"/"attempt",
        "elapsed_days": int or None,
        "limit_days": int or None,
        "attempt_count": int or None,
        "limit_attempts": int or None,
      }
    """
    desc_lower = description.lower() if isinstance(description, str) else ""
    cat_lower = (category_raw or "").lower()
    type_lower = (ticket_type or "").lower()
    subject_lower = (ticket_subject or "").lower()

    def category_or_subject_match(rule):
        return (
            cat_lower in rule.get("trigger_categories", [])
            or type_lower in rule.get("trigger_categories", [])
            or subject_lower in rule.get("trigger_subjects", [])
        )

    def matches(rule, keyword_field="trigger_keywords"):
        return _keyword_in_text(rule.get(keyword_field, []), desc_lower) and category_or_subject_match(rule)

    blank_extras = {
        "elapsed_days": None, "limit_days": None,
        "attempt_count": None, "limit_attempts": None,
    }

    # 1. CONTRADICTION -- "marked done/resolved" + "but not actually done" both present
    for rule in CONTRADICTION_RULES:
        if not category_or_subject_match(rule):
            continue
        status_hit = any(re.search(pat, desc_lower) for pat in rule["status_patterns"])
        contradiction_hit = _contradiction_keyword_in_text(rule["contradiction_keywords"], desc_lower)
        if status_hit and contradiction_hit:
            return {
                "triggered": True,
                "decision": "no",
                "reason": rule["reason"],
                "rule_name": rule["name"],
                "rule_type": "contradiction",
                **blank_extras,
            }

    # 2. SEVERITY -- always escalate to human if matched, no time/attempt math needed
    for rule in SEVERITY_RULES:
        if matches(rule):
            return {
                "triggered": True,
                "decision": "no",
                "reason": rule["reason"],
                "rule_name": rule["name"],
                "rule_type": "severity",
                **blank_extras,
            }

    # 3. DAY-BASED -- escalate if elapsed time exceeds the policy window,
    #    otherwise force "yes" (normal waiting period, AI can handle it)
    for rule in DAY_RULES:
        if not matches(rule):
            continue
        elapsed_days = extract_elapsed_days(description, reference_date=reference_date)
        if elapsed_days is None:
            continue  # topic matched but no day-count parsed -> fall through to ML
        exceeded = elapsed_days > rule["max_days"]
        return {
            "triggered": True,
            "decision": "no" if exceeded else "yes",
            "reason": rule["reason_exceeded"] if exceeded else rule["reason_within"],
            "rule_name": rule["name"],
            "rule_type": "day",
            "elapsed_days": elapsed_days, "limit_days": rule["max_days"],
            "attempt_count": None, "limit_attempts": None,
        }

    # 4. ATTEMPT-BASED -- escalate if customer already tried more than the
    #    threshold, otherwise force "yes" (few/no attempts yet, AI can guide them)
    for rule in ATTEMPT_RULES:
        if not matches(rule):
            continue
        attempt_count = extract_attempt_count(description)
        if attempt_count is None:
            continue
        exceeded = attempt_count > rule["max_attempts"]
        return {
            "triggered": True,
            "decision": "no" if exceeded else "yes",
            "reason": rule["reason_exceeded"] if exceeded else rule["reason_within"],
            "rule_name": rule["name"],
            "rule_type": "attempt",
            "elapsed_days": None, "limit_days": None,
            "attempt_count": attempt_count, "limit_attempts": rule["max_attempts"],
        }

    return None


def train_and_select_best_model(csv_path):
    """Loads the dataset, trains models, outputs metrics, and returns the best pipeline."""
    print(f"Loading dataset from: {csv_path}...")
    df = pd.read_csv(csv_path)

    df_labeled = df.dropna(subset=['Customer Satisfaction Rating']).copy()

    scores = np.zeros(len(df_labeled))

    priority_map = {'Low': 0.4, 'Medium': 0.1, 'High': -0.2, 'Critical': -0.5}
    scores += df_labeled['Ticket Priority'].map(priority_map).fillna(0)

    channel_map = {'Chat': 0.15, 'Phone': 0.1, 'Email': -0.05, 'Social media': -0.15}
    scores += df_labeled['Ticket Channel'].map(channel_map).fillna(0)

    type_map = {'Billing inquiry': 0.1, 'Product inquiry': 0.1, 'Cancellation request': -0.1,
                'Refund request': -0.1, 'Technical issue': -0.1}
    scores += df_labeled['Ticket Type'].map(type_map).fillna(0)

    desc = df_labeled['Ticket Description'].str.lower().fillna("")
    pos_keywords = ["thank", "great", "awesome", "solved", "resolved", "helpful", "good", "perfect", "appreciate", "fix"]
    neg_keywords = ["broken", "crash", "error", "fail", "useless", "terrible", "worst", "waiting", "angry", "disappointed", "refund", "cancellation", "bug"]

    pos_counts = np.sum([desc.str.contains(w).astype(int) for w in pos_keywords], axis=0)
    neg_counts = np.sum([desc.str.contains(w).astype(int) for w in neg_keywords], axis=0)
    scores += pos_counts * 0.4
    scores -= neg_counts * 0.4

    np.random.seed(42)
    noise = np.random.normal(0, 0.1, size=len(df_labeled))
    scores += noise

    df_labeled['Satisfied'] = (scores >= 0.0).astype(int)

    X = df_labeled[['Product Purchased', 'Ticket Type', 'Ticket Subject', 'Ticket Priority', 'Ticket Channel', 'Ticket Description']]
    y = df_labeled['Satisfied']

    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    preprocessor = ColumnTransformer(
        transformers=[
            ('text', TfidfVectorizer(max_features=1000, stop_words='english'), 'Ticket Description'),
            ('cat', OneHotEncoder(handle_unknown='ignore'), ['Product Purchased', 'Ticket Type', 'Ticket Subject', 'Ticket Priority', 'Ticket Channel'])
        ]
    )

    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier

    models = {
        'Logistic Regression': LogisticRegression(max_iter=1000, random_state=42),
        'Random Forest': RandomForestClassifier(n_estimators=100, random_state=42)
    }

    if XGBOOST_AVAILABLE:
        models['XGBoost'] = XGBClassifier(use_label_encoder=False, eval_metric='logloss', random_state=42)
    else:
        print("[Note] XGBoost package not found or failed to load. Skipping XGBoost model.")

    metrics = {}
    trained_pipelines = {}

    print("\nTraining and evaluating models...")
    for name, clf in models.items():
        pipeline = Pipeline(steps=[
            ('preprocessor', preprocessor),
            ('classifier', clf)
        ])

        pipeline.fit(X_train, y_train)
        trained_pipelines[name] = pipeline

        y_pred = pipeline.predict(X_val)
        y_proba = pipeline.predict_proba(X_val)[:, 1]

        acc = accuracy_score(y_val, y_pred)
        prec = precision_score(y_val, y_pred, zero_division=0)
        rec = recall_score(y_val, y_pred, zero_division=0)
        f1 = f1_score(y_val, y_pred, zero_division=0)
        auc = roc_auc_score(y_val, y_proba)

        metrics[name] = {
            'Accuracy': acc,
            'Precision': prec,
            'Recall': rec,
            'F1-Score': f1,
            'ROC AUC': auc
        }

    print("\n" + "=" * 80)
    print("MODEL PERFORMANCE COMPARISON (Validation Set)")
    print("=" * 80)
    print(f"{'Model':<25} | {'Accuracy':<10} | {'Precision':<10} | {'Recall':<10} | {'F1-Score':<10} | {'ROC AUC':<10}")
    print("-" * 80)
    for name, score in metrics.items():
        print(f"{name:<25} | {score['Accuracy']:<10.4f} | {score['Precision']:<10.4f} | {score['Recall']:<10.4f} | {score['F1-Score']:<10.4f} | {score['ROC AUC']:<10.4f}")
    print("=" * 80 + "\n")

    best_model_name = max(metrics, key=lambda k: metrics[k]['F1-Score'])
    print(f"--> Selected '{best_model_name}' as the best model based on F1-score.")

    print("Re-fitting the best model on the complete labeled dataset...")
    best_pipeline = Pipeline(steps=[
        ('preprocessor', preprocessor),
        ('classifier', models[best_model_name])
    ])
    best_pipeline.fit(X, y)

    return best_pipeline, best_model_name


def predict_ticket(best_pipeline, mapped, threshold, reference_date=None):
    """
    Full prediction flow: rule engine first, ML model only as fallback when
    no rule's topic applies at all (e.g. Product compatibility/Product
    recommendation outside of their contradiction-pattern cases -- those
    two remain pure ML for everything else, by design). Returns a dict
    with decision, source ("rule" or "ml"), probability (if applicable),
    and a human-readable reason.
    """
    rule_result = evaluate_business_rules(
        category_raw=mapped["_category_raw"],
        ticket_type=mapped["Ticket Type"],
        ticket_subject=mapped["Ticket Subject"],
        description=mapped["Ticket Description"],
        reference_date=reference_date,
    )

    if rule_result is not None:
        return {
            "decision": rule_result["decision"],
            "source": "rule",
            "rule_name": rule_result["rule_name"],
            "rule_type": rule_result["rule_type"],
            "elapsed_days": rule_result["elapsed_days"],
            "limit_days": rule_result["limit_days"],
            "attempt_count": rule_result["attempt_count"],
            "limit_attempts": rule_result["limit_attempts"],
            "reason": rule_result["reason"],
            "probability": None,
        }

    # No rule's topic matched at all -- pure ML fallback.
    input_df = pd.DataFrame([{k: v for k, v in mapped.items() if not k.startswith("_")}])
    prob = best_pipeline.predict_proba(input_df)[0, 1]
    decision = "yes" if prob >= threshold else "no"

    return {
        "decision": decision,
        "source": "ml",
        "rule_name": None,
        "rule_type": None,
        "elapsed_days": None,
        "limit_days": None,
        "attempt_count": None,
        "limit_attempts": None,
        "reason": "Model-based prediction from historical ticket patterns (no specific policy rule applied).",
        "probability": float(prob),
    }


def main():
    parser = argparse.ArgumentParser(description="Predict whether AI can resolve a customer support ticket.")
    parser.add_argument("--csv", type=str, default="customer_support_tickets.csv", help="Path to the customer support tickets CSV file.")
    parser.add_argument("--category", type=str, default=None, help="Ticket category.")
    parser.add_argument("--subject", type=str, default=None, help="Ticket subject.")
    parser.add_argument("--priority", type=str, default=None, help="Ticket priority (Low, Medium, High, Critical).")
    parser.add_argument("--channel", type=str, default=None, help="Contact channel (Phone, Email, Social media, Chat).")
    parser.add_argument("--product", type=str, default=None, help="Product name.")
    parser.add_argument("--description", type=str, default=None, help="Description of the problem.")
    parser.add_argument("--threshold", type=float, default=None, help="Classification probability threshold (0.0 to 1.0).")
    parser.add_argument("--retrain", action="store_true", help="Force re-training of the model.")
    args = parser.parse_args()

    csv_path = args.csv
    if not os.path.exists(csv_path):
        fallback_path = r"c:\Users\Asus\Desktop\AI\customer_support_tickets.csv"
        if os.path.exists(fallback_path):
            csv_path = fallback_path
        else:
            print(f"Error: Dataset not found at '{csv_path}' or '{fallback_path}'. Please check file path.")
            sys.exit(1)

    model_path = "best_model.pkl"
    if os.path.exists(model_path) and not args.retrain:
        print(f"Loading pre-trained model pipeline from '{model_path}'...")
        try:
            with open(model_path, 'rb') as f:
                saved_data = pickle.load(f)
            best_pipeline = saved_data['pipeline']
            best_model_name = saved_data['model_name']
        except Exception as e:
            print(f"Could not load pre-trained model due to: {e}. Retraining...")
            best_pipeline, best_model_name = train_and_select_best_model(csv_path)
            with open(model_path, 'wb') as f:
                pickle.dump({'pipeline': best_pipeline, 'model_name': best_model_name}, f)
    else:
        best_pipeline, best_model_name = train_and_select_best_model(csv_path)
        with open(model_path, 'wb') as f:
            pickle.dump({'pipeline': best_pipeline, 'model_name': best_model_name}, f)
        print(f"Saved best model pipeline to '{model_path}'")

    category = args.category if args.category is not None else DEFAULT_INPUTS["category"]
    subject = args.subject if args.subject is not None else DEFAULT_INPUTS["subject"]
    priority = args.priority if args.priority is not None else DEFAULT_INPUTS["priority"]
    channel = args.channel if args.channel is not None else DEFAULT_INPUTS["channel"]
    product = args.product if args.product is not None else DEFAULT_INPUTS["product"]
    description = args.description if args.description is not None else DEFAULT_INPUTS["description"]
    threshold = args.threshold if args.threshold is not None else DEFAULT_INPUTS["threshold"]

    mapped = map_inputs(
        category=category,
        subject=subject,
        priority=priority,
        channel=channel,
        product=product,
        description=description
    )

    result = predict_ticket(best_pipeline, mapped, threshold)

    print("\n" + "=" * 55)
    print("CUSTOMER SUPPORT TICKET PREDICTION RESULT")
    print("=" * 55)
    print(f"Category (Mapped to Ticket Type): {mapped['Ticket Type']}")
    print(f"Subject (Mapped):              {mapped['Ticket Subject']}")
    print(f"Priority (Mapped):             {mapped['Ticket Priority']}")
    print(f"Channel (Mapped):              {mapped['Ticket Channel']}")
    print(f"Product (Mapped):              {mapped['Product Purchased']}")
    print(f"Description (Truncated):       {mapped['Ticket Description'][:60]}...")
    print("-" * 55)
    print(f"Decision Source:               {result['source'].upper()} ({result['rule_name'] or 'n/a'})")
    if result['elapsed_days'] is not None:
        print(f"Elapsed Days Parsed:           {result['elapsed_days']} (policy limit: {result['limit_days']})")
    if result['attempt_count'] is not None:
        print(f"Attempt Count Parsed:          {result['attempt_count']} (threshold: {result['limit_attempts']})")
    if result['source'] == 'ml':
        print(f"Best Model Used:               {best_model_name}")
        print(f"Predicted Probability:         {result['probability']:.4f}")
        print(f"Decision Threshold:            {threshold:.4f}")
    print(f"Reason:                         {result['reason']}")
    print("-" * 55)
    print(f"PREDICTION:                    {result['decision'].upper()}")
    print("=" * 55)

    print(f"\n{result['decision']}")


if __name__ == "__main__":
    main()
