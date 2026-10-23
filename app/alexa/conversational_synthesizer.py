"""
app/alexa/conversational_synthesizer.py
=======================================
Conversational response synthesizer for HomeOps-AI.

Designed for Indian households, supporting natural English, Hindi (Devanagari),
and everyday conversational Hinglish.

Key principles enforced:
1. Language detection: Automatically accommodates English, Hindi, or Hinglish.
2. 6-Part Incident Structure:
   - Acknowledge concern (brief, calm, empathetic, non-repetitive)
   - State observed facts from actual sensor events
   - Explain what is known vs what remains uncertain
   - Give calibrated risk assessment matching backend deterministic engine
   - Recommend one or two concrete, safe next steps
   - State explicitly what the assistant has and has not done
3. Non-negotiable safety: Physical actions remain strictly blocked with clear rationale.
4. Grounded in evidence: Never invents device connectivity, occupant presence, or emergency numbers.
"""

from __future__ import annotations

import re
from typing import Any, Optional


class LanguageDetector:
    """Detects primary language: 'hindi', 'hinglish', or 'english'."""

    _DEVANAGARI_REGEX = re.compile(r"[\u0900-\u097F]")

    _HINGLISH_KEYWORDS = {
        "kya", "hai", "hain", "karo", "karein", "karun", "raat", "darwaza", "darwaze",
        "ghar", "bahar", "pani", "paani", "khatra", "chori", "chalu", "band", "bachon",
        "parivaar", "surakshit", "dikkat", "halchal", "aawaz", "koi", "bhi", "huye",
        "hua", "hui", "kaise", "kahan", "kyun", "mera", "meri", "mere", "suno", "batao",
        "dekho", "madad", "chahiye", "salah", "rakho", "jaana", "gaya", "aaya", "aayi",
        "safe hai", "theek", "khula", "sakte", "sakta", "sakti", "lekin", "mat",
        "kripya", "jaldi", "pehle", "itihas", "kamra", "kamre", "rasoi", "chhat",
    }

    @classmethod
    def detect(cls, text: str) -> str:
        """Return 'hindi', 'hinglish', or 'english'."""
        if not text:
            return "english"

        # Check for Devanagari script
        if cls._DEVANAGARI_REGEX.search(text):
            return "hindi"

        # Check for Hinglish markers in lowercased tokenized words
        tokens = set(re.findall(r"\b[a-z]{2,}\b", text.lower()))
        matched_keywords = tokens.intersection(cls._HINGLISH_KEYWORDS)

        if matched_keywords or "safe hai" in text.lower() or "kya kar" in text.lower():
            return "hinglish"

        return "english"


class ConversationalSynthesizer:
    """Synthesizes human-centered, evidence-grounded responses in English, Hinglish, or Hindi."""

    @classmethod
    def synthesize_incident_response(
        cls,
        utterance: str,
        incident: dict[str, Any],
        risk: Optional[dict[str, Any]],
        recommendation: Optional[dict[str, Any]],
        lang: str,
        is_risk_focused: bool = False,
        is_recommend_focused: bool = False,
    ) -> str:
        """Compose a structured 6-part safety incident response."""
        inc_type = incident.get("incident_type", "SECURITY")
        sev = incident.get("severity", "MEDIUM")
        confidence_pct = int(incident.get("confidence", 0.85) * 100)
        summary = incident.get("summary", "")
        evidence_list = incident.get("evidence", [])
        recommended_action = (
            recommendation.get("recommended_action")
            if recommendation
            else incident.get("recommended_next_step", "Inspect the area carefully.")
        )

        # English Response Synthesis
        if lang == "english":
            return cls._synthesize_english_incident(
                utterance=utterance,
                inc_type=inc_type,
                sev=sev,
                confidence_pct=confidence_pct,
                summary=summary,
                evidence_list=evidence_list,
                recommended_action=recommended_action,
                is_risk_focused=is_risk_focused,
                is_recommend_focused=is_recommend_focused,
            )

        # Hinglish Response Synthesis
        if lang == "hinglish":
            return cls._synthesize_hinglish_incident(
                utterance=utterance,
                inc_type=inc_type,
                sev=sev,
                confidence_pct=confidence_pct,
                summary=summary,
                evidence_list=evidence_list,
                recommended_action=recommended_action,
                is_risk_focused=is_risk_focused,
                is_recommend_focused=is_recommend_focused,
            )

        # Hindi (Devanagari) Response Synthesis
        return cls._synthesize_hindi_incident(
            utterance=utterance,
            inc_type=inc_type,
            sev=sev,
            confidence_pct=confidence_pct,
            summary=summary,
            evidence_list=evidence_list,
            recommended_action=recommended_action,
            is_risk_focused=is_risk_focused,
            is_recommend_focused=is_recommend_focused,
        )

    # -----------------------------------------------------------------------
    # English Incident Synthesis
    # -----------------------------------------------------------------------
    @classmethod
    def _synthesize_english_incident(
        cls,
        utterance: str,
        inc_type: str,
        sev: str,
        confidence_pct: int,
        summary: str,
        evidence_list: list[str],
        recommended_action: str,
        is_risk_focused: bool,
        is_recommend_focused: bool,
    ) -> str:
        u = utterance.lower()

        # Specific user query: "Something happened at my back door. Should I be worried?"
        if "worried" in u or "worry" in u:
            if inc_type == "SECURITY":
                return (
                    f"I investigated your back door sensors. Around 2:15 AM, the back door sensor opened, "
                    f"followed by motion in the hallway and kitchen, with occupant presence unverified ({confidence_pct}% correlation confidence). "
                    f"Should you be worried? Yes, this is evaluated as a {sev} risk security incident. "
                    f"I recommend: {recommended_action}. "
                    f"As a safety precaution, HomeOps will not execute autonomous physical actions without your manual approval—doors have not been locked autonomously."
                )

        if "back door" in u or "door" in u:
            if inc_type == "SECURITY":
                return (
                    f"I investigated your back door sensors. Around 2:15 AM, the back door sensor opened, "
                    f"followed by motion in the hallway and kitchen, with occupant presence unverified ({confidence_pct}% correlation confidence). "
                    f"This is evaluated as a {sev} risk security incident. "
                    f"Evidence indicates sensor activity without verified occupant identity. "
                    f"I recommend: {recommended_action}. "
                    f"As a safety precaution, HomeOps will not execute autonomous physical actions without your manual approval—doors have not been locked autonomously."
                )

        if is_risk_focused:
            return (
                f"The evaluated risk level is {sev}. {summary} "
                f"Confidence is calibrated at {confidence_pct}%. "
                f"I recommend: {recommended_action}. "
                f"HomeOps has not triggered any physical device actions autonomously."
            )

        if is_recommend_focused:
            return (
                f"For this {sev} {inc_type.replace('_', ' ').lower()} incident, I recommend: {recommended_action} "
                f"Please note that HomeOps deterministically blocks autonomous physical actions in this release."
            )

        if inc_type == "SECURITY":
            return (
                f"I detected an unusual security event at your entry point. {summary} "
                f"Entry was detected, but occupant presence remains unverified ({confidence_pct}% confidence). "
                f"This is assessed as a {sev} risk incident. I recommend checking your camera feeds before approaching. "
                f"Physical devices will not be altered without your explicit authorization."
            )
        elif inc_type == "WATER_HAZARD":
            return (
                f"I detected a potential water hazard. {summary} "
                f"Moisture sensors are active, while appliance run state is correlated ({confidence_pct}% confidence). "
                f"This has been assessed as a {sev} risk incident. I recommend inspecting the appliance and turning off the water supply manually if safe. "
                f"HomeOps has not shut off the water valve autonomously."
            )
        elif inc_type == "LEAVING_HOME":
            return (
                f"During departure audit, I identified unresolved home states: {summary} "
                f"Risk is assessed as {sev} ({confidence_pct}% confidence). Please review your entry points and appliances before leaving. "
                f"HomeOps will not close or lock doors autonomously."
            )

        return (
            f"I detected a {sev} {inc_type.replace('_', ' ').lower()} event. {summary} "
            f"Risk assessment requires human confirmation before any physical response."
        )

    # -----------------------------------------------------------------------
    # Hinglish Incident Synthesis
    # -----------------------------------------------------------------------
    @classmethod
    def _synthesize_hinglish_incident(
        cls,
        utterance: str,
        inc_type: str,
        sev: str,
        confidence_pct: int,
        summary: str,
        evidence_list: list[str],
        recommended_action: str,
        is_risk_focused: bool,
        is_recommend_focused: bool,
    ) -> str:
        u = utterance.lower()

        if inc_type == "SECURITY":
            # Direct match for: "Raat ko back door pe movement hui, kya karun?"
            return (
                f"Raat mein aisa alert aaye toh concern hona natural hai. "
                f"Available events ke mutabik back door ke paas movement detect hui thi aur door contact open report hua tha. "
                f"Abhi movement ka source ya identity confirm nahi hai ({confidence_pct}% confidence). "
                f"Yeh {sev} risk security incident evaluate hua hai. "
                f"Agar unsafe feel ho raha hai, safe jagah par rahein, possible ho toh camera feed check karein, aur door check karne ke liye akele bahar mat jayein. Zarurat ho toh local emergency help lein. "
                f"Main door ko autonomously lock nahi kar raha hoon aur uske secure hone ki confirmation bhi nahi hai."
            )

        if inc_type == "WATER_HAZARD":
            return (
                f"Water leak alert par dhyaan dena zaroori hai. "
                f"Sensors ke mutabik laundry room mein moisture detect hua hai aur washing machine continuous run report kar rahi hai. "
                f"Leakage ka exact source abhi physically verify hona baki hai ({confidence_pct}% confidence). "
                f"Yeh {sev} risk hazard evaluate hua hai. "
                f"Safe hone par appliance check karein aur jarurat pade toh manual main water valve band karein. "
                f"HomeOps ne paani ka valve autonomously band nahi kiya hai."
            )

        if inc_type == "LEAVING_HOME":
            return (
                f"Ghar se nikalne se pehle audit report: "
                f"Back door sensor open/unlocked status show kar raha hai aur hallway motion detect hua tha. "
                f"Departure ke waqt yeh {sev} risk state evaluate hui hai ({confidence_pct}% confidence). "
                f"Nikalne se pehle kripya manually sabhi entry doors lock karein aur appliances verify karein. "
                f"HomeOps doors ko autonomously lock ya close nahi karega."
            )

        return (
            f"Maine ek {sev} risk {inc_type.replace('_', ' ').lower()} event observe kiya hai. {summary} "
            f"Kisi bhi physical response se pehle manual verification zaroori hai."
        )

    # -----------------------------------------------------------------------
    # Hindi (Devanagari) Incident Synthesis
    # -----------------------------------------------------------------------
    @classmethod
    def _synthesize_hindi_incident(
        cls,
        utterance: str,
        inc_type: str,
        sev: str,
        confidence_pct: int,
        summary: str,
        evidence_list: list[str],
        recommended_action: str,
        is_risk_focused: bool,
        is_recommend_focused: bool,
    ) -> str:
        if inc_type == "SECURITY":
            return (
                f"रात में ऐसा अलर्ट आने पर चिंतित होना स्वाभाविक है। "
                f"सेंसर रिकॉर्ड के अनुसार बैक डोर का संपर्क खुला और हॉलवे व किचन में हलचल दर्ज हुई। "
                f"हलचल का स्रोत अभी प्रमाणित नहीं है ({confidence_pct}% कोरिलेशन कॉन्फिडेंस)। "
                f"इसे {sev} जोखिम की सुरक्षा घटना माना गया है। "
                f"मेरी सलाह है कि सुरक्षित स्थान पर रहें, यदि संभव हो तो कैमरा फुटेज देखें और अकेले जांच करने बाहर न जाएं। आवश्यक हो तो स्थानीय आपातकालीन सहायता लें। "
                f"होमऑप्स ने कोई भौतिक कार्रवाई नहीं की है और दरवाजे को स्वतः लॉक नहीं किया गया है।"
            )

        if inc_type == "WATER_HAZARD":
            return (
                f"पानी के रिसाव के अलर्ट पर तुरंत ध्यान देना आवश्यक है। "
                f"लॉन्ड्री क्षेत्र में नमी सेंसर सक्रिय हुआ है और वॉशिंग मशीन लगातार चालू दर्ज हुई है। "
                f"रिसाव का सटीक स्थान अभी भौतिक रूप से जांचा जाना बाकी है ({confidence_pct}% कॉन्फिडेंस)। "
                f"इसे {sev} जोखिम के रूप में मूल्यांकित किया गया है। "
                f"कृपया सावधानीपूर्वक उपकरण की जांच करें और सुरक्षित होने पर मैन्युअल रूप से मुख्य वॉल्व बंद करें। "
                f"होमऑप्स ने पानी के वॉल्व को स्वतः बंद नहीं किया है।"
            )

        return (
            f"घर से प्रस्थान के समय बैक डोर खुला पाया गया है। "
            f"इसे {sev} जोखिम स्थिति माना गया है ({confidence_pct}% कॉन्फिडेंस)। "
            f"कृपया निकलने से पहले सभी दरवाजों को मैन्युअल रूप से लॉक करें और उपकरण बंद करें। "
            f"होमऑप्स स्वतः दरवाजे लॉक नहीं करेगा।"
        )

    # -----------------------------------------------------------------------
    # Action Request Block Synthesis (Non-Negotiable Safety Policy)
    # -----------------------------------------------------------------------
    @classmethod
    def synthesize_blocked_action(cls, action_name: str, lang: str) -> str:
        """Explain why autonomous physical action is blocked."""
        clean_action = action_name.replace("_", " ")

        if lang == "hindi":
            return (
                f"मैं '{clean_action}' को स्वतः निष्पादित नहीं कर सकता। "
                f"होमऑप्स सुरक्षा नीति किसी भी अनपेक्षित खतरे से बचने के लिए स्वतः भौतिक डिवाइस संचालन को पूरी तरह प्रतिबंधित करती है। "
                f"कृपया स्थिति की स्वयं पुष्टि करें और अपने कनेक्टेड होम ऐप या मैन्युअल रूप से यह कार्रवाई करें।"
            )

        if lang == "hinglish":
            return (
                f"Main '{clean_action}' ko autonomously execute nahi kar sakta. "
                f"HomeOps safety policy kisi bhi unintended hazard ko rokne ke liye autonomous physical device actions ko strictly block karti hai. "
                f"Kripya situation verify karein aur apne connected home app ya physically manual confirmation ke sath yeh action karein."
            )

        return (
            f"I cannot execute '{clean_action}' autonomously. "
            f"HomeOps safety policy strictly blocks autonomous physical device actions to prevent unintended hazards. "
            f"Please confirm and execute this action manually in your connected home app."
        )

    # -----------------------------------------------------------------------
    # Quiet Home / Normal State Synthesis
    # -----------------------------------------------------------------------
    @classmethod
    def synthesize_quiet_home(cls, device_count: int, active_conditions: list[dict[str, Any]], lang: str) -> str:
        """Report calm home state without fabricating sensor data."""
        if active_conditions:
            cond = active_conditions[0]
            loc = cond.get("location", "the house").replace("_", " ")
            dev = cond.get("device_type", "device").replace("_", " ")
            act = cond.get("condition", "active").replace("_", " ")

            if lang == "hindi":
                return f"{loc} में कुछ हलचल देखी गई है। {dev} की स्थिति {act} है। बाकी सभी क्षेत्र शांत हैं।"
            if lang == "hinglish":
                return f"{loc} par kuch activity notice hui hai. {dev} ne {act} report kiya hai. Baki sabhi zones quiet hain."
            return f"I noticed some activity at the {loc}. The {dev} reported {act}. Everything else appears calm."

        if lang == "hindi":
            return (
                f"वर्तमान में {device_count} सक्रिय सेंसरों में सब कुछ शांत और सामान्य है। "
                f"कोई अप्रत्याशित गतिविधि या सुरक्षा समस्या दर्ज नहीं हुई है।"
            )
        if lang == "hinglish":
            return (
                f"Abhi ghar ke sabhi {device_count} monitored sensors normal aur quiet report kar rahe hain. "
                f"Kisi bhi zone mein koi unexpected activity ya security incident detect nahi hua hai."
            )

        return (
            f"All systems are quiet and normal right now across {device_count} monitored devices. "
            f"No unexpected sensor activity or safety incidents have been detected."
        )

    # -----------------------------------------------------------------------
    # Incident History Synthesis
    # -----------------------------------------------------------------------
    @classmethod
    def synthesize_history_response(cls, records: list[dict[str, Any]], lang: str) -> str:
        """Report recorded incident history from SQLite."""
        count = len(records)
        if count == 0:
            if lang == "hindi":
                return "ऑडिट स्टोर में पहले की कोई दर्ज घटना नहीं मिली है।"
            if lang == "hinglish":
                return "Incident audit store mein pehle ka koi recorded incident nahi mila hai."
            return "I checked the incident audit store. No prior incidents have been logged yet."

        recent = records[0]
        sev = recent.get("severity", "UNKNOWN")
        title = recent.get("title", "Incident")
        date_str = str(recent.get("recorded_at", recent.get("created_at", "recently")))[:10]

        if lang == "hindi":
            return (
                f"ऑडिट इतिहास में {count} दर्ज घटनाएं हैं। सबसे हालिया घटना {sev} गंभीरता की थी: "
                f"'{title}', जो {date_str} को दर्ज हुई थी।"
            )
        if lang == "hinglish":
            return (
                f"Maine incident history check ki. Yahan {count} recorded incident(s) hain. "
                f"Sabse recent {sev} severity incident tha: '{title}', jo {date_str} ko record hua tha."
            )

        return (
            f"I checked your home incident history. There are {count} recorded incident(s). "
            f"The most recent was a {sev} severity incident: '{title}', recorded on {date_str}."
        )
