import re


def is_small_talk(text: str) -> bool:
    normalized = " ".join(re.findall(r"\w+", text.lower()))
    return normalized in {
        "hi",
        "hello",
        "hey",
        "hi there",
        "hello there",
        "amazing",
        "great",
        "awesome",
        "nice",
        "ok",
        "okay",
        "thanks",
        "thank you",
        "good morning",
        "good evening",
    }


def contextual_gaps(
    text: str,
    category: str,
    has_output: bool,
    has_constraints: bool,
) -> list[dict[str, str]]:
    lowered = text.lower()
    topic = " ".join(text.split())[:110].rstrip(".?!")

    def gap(dimension: str, title: str, question: str, critical: bool = False) -> dict[str, str]:
        return {
            "dimension": dimension,
            "title": title,
            "description": f"A decision is needed to complete this request: {topic}",
            "severity": "critical" if critical else "important",
            "importance": "high",
            "question_target": question,
        }

    if is_small_talk(text):
        return [
            gap(
                "objective",
                "Your goal",
                "What would you like help creating, understanding, or fixing?",
                True,
            )
        ]
    # An explanation, translation, or small creative request already describes its deliverable.
    if re.match(
        r"\s*(explain|define|translate|what (is|are)|write .*\b(poem|haiku|joke)\b)", lowered
    ):
        return []
    if category == "software_development":
        gaps = []
        if not has_constraints and not re.search(
            r"\b(python|javascript|typescript|react|next|fastapi|django|flutter|java|node|html)\b",
            lowered,
        ):
            gaps.append(
                gap(
                    "constraints",
                    "Platform and technology",
                    f"For “{topic}”, which platform or technology should we use? "
                    "Say 'recommend one' if you are unsure.",
                    True,
                )
            )
        if len(text.split()) < 18:
            gaps.append(
                gap(
                    "requirements",
                    "Essential features",
                    f"What are the essential features for “{topic}”, and who will use it?",
                )
            )
        return gaps
    if "launch" in lowered or "workshop" in lowered:
        gaps = []
        if len(text.split()) < 22:
            question = (
                "What are you launching, and what outcome should the launch achieve?"
                if "launch" in lowered
                else "What is the workshop topic and the outcome participants should achieve?"
            )
            gaps.append(gap("context", "Scope and goal", question, True))
        if not has_output:
            gaps.append(
                gap(
                    "output",
                    "Plan audience and detail",
                    f"For “{topic}”, who will use the plan and how much detail do they need?",
                )
            )
        return gaps
    if category == "data_analysis" and not re.search(
        r"\b(csv|dataset|attached|provided|sales data|columns)\b", lowered
    ):
        return [
            gap(
                "context",
                "Data source",
                f"Which data should I analyze for “{topic}”? Share the columns or a sample.",
                True,
            )
        ]
    if category == "writing" and not re.search(r"\b(for|to|about|on)\s+\w+", lowered):
        return [
            gap(
                "objective",
                "Writing topic",
                f"What should “{topic}” cover, and who is it for?",
                True,
            )
        ]
    if category == "marketing" and not re.search(
        r"\b(customer|audience|target|restaurant|business|product|brand)\b", lowered
    ):
        return [
            gap(
                "audience",
                "Customers and offer",
                f"Which product and customers should “{topic}” focus on?",
                True,
            )
        ]
    if not has_output:
        return [
            gap(
                "output",
                "Deliverable",
                f"For “{topic}”, would you prefer a step-by-step answer, "
                "a short summary, or another deliverable?",
            )
        ]
    return []
