#!/usr/bin/env python3
"""Batch-insert ~161 new skills into skills.db across 9 categories."""

import argparse
import json
import sqlite3
import os

DB_PATH = "/home/damien809/agent-service/skills.db"

def schema(desc):
    return json.dumps({
        "type": "object",
        "properties": {"input": {"type": "string", "description": desc}},
        "required": ["input"]
    })


SKILLS = [
    # =========================================================================
    # HEALTHCARE (30)
    # =========================================================================
    (
        "symptom_checker",
        "Analyze reported symptoms and suggest possible conditions with urgency levels",
        "healthcare",
        "batch_v2",
        "You are an expert medical triage assistant. Given the following symptoms and patient context, analyze the possible conditions, rank them by likelihood, and indicate urgency level (emergency, urgent, routine). Always remind the user this is not a substitute for professional medical advice.\n\nInput: {input}\n\nReturn JSON with keys: possible_conditions (list of {condition, likelihood, urgency}), recommended_action, disclaimer.",
        schema("Comma-separated list of symptoms, optionally with age/sex/duration")
    ),
    (
        "medication_interaction_checker",
        "Check for potential interactions between multiple medications",
        "healthcare",
        "batch_v2",
        "You are an expert pharmacology advisor. Given a list of medications, identify potential drug-drug interactions, severity levels, and recommendations. Always include a disclaimer to consult a pharmacist.\n\nInput: {input}\n\nReturn JSON with keys: interactions (list of {drug_pair, severity, description, recommendation}), safe_combinations, disclaimer.",
        schema("Comma-separated list of medication names the patient is taking")
    ),
    (
        "nutrition_plan_generator",
        "Generate a personalized weekly nutrition plan based on dietary goals and restrictions",
        "healthcare",
        "batch_v2",
        "You are an expert nutritionist. Based on the user's dietary goals, restrictions, and preferences, create a detailed 7-day meal plan with macronutrient breakdowns. Include grocery list and meal prep tips.\n\nInput: {input}\n\nReturn JSON with keys: weekly_plan (list of {day, meals: {breakfast, lunch, dinner, snacks}}), daily_macros, grocery_list, meal_prep_tips.",
        schema("Dietary goals, restrictions, preferences, calorie target, and any allergies")
    ),
    (
        "fitness_routine_builder",
        "Create a customized fitness routine based on goals, fitness level, and available equipment",
        "healthcare",
        "batch_v2",
        "You are an expert fitness coach. Design a structured workout routine tailored to the user's fitness level, goals, available equipment, and time constraints. Include warm-up, main workout, and cool-down.\n\nInput: {input}\n\nReturn JSON with keys: routine_name, frequency, exercises (list of {name, sets, reps, rest_seconds, notes}), warm_up, cool_down, progression_tips.",
        schema("Fitness level, goals (strength/cardio/flexibility), available equipment, days per week")
    ),
    (
        "mental_health_assessment",
        "Provide a preliminary mental wellness check with coping strategies and resource recommendations",
        "healthcare",
        "batch_v2",
        "You are an expert mental health advisor. Based on the user's described feelings and experiences, provide a compassionate wellness assessment, suggest evidence-based coping strategies, and recommend when to seek professional help. This is not a clinical diagnosis.\n\nInput: {input}\n\nReturn JSON with keys: wellness_indicators, areas_of_concern, coping_strategies, professional_resources, crisis_hotlines, disclaimer.",
        schema("Description of current feelings, stress levels, sleep patterns, and any concerns")
    ),
    (
        "medical_terminology_explainer",
        "Translate complex medical terms and reports into plain language",
        "healthcare",
        "batch_v2",
        "You are an expert medical communicator. Take the provided medical terminology, diagnoses, or report excerpts and explain them in clear, accessible language that a non-medical person can understand.\n\nInput: {input}\n\nReturn JSON with keys: terms_explained (list of {term, plain_language, context}), summary, follow_up_questions_to_ask_doctor.",
        schema("Medical terms, diagnosis codes, or report excerpts to explain")
    ),
    (
        "patient_intake_form_generator",
        "Generate a customized patient intake form for a specific medical specialty",
        "healthcare",
        "batch_v2",
        "You are an expert healthcare administrator. Create a comprehensive patient intake form tailored to the specified medical specialty, including relevant medical history questions, consent sections, and insurance information fields.\n\nInput: {input}\n\nReturn JSON with keys: form_title, specialty, sections (list of {section_name, fields: list of {label, type, required, options}}), consent_text, hipaa_notice.",
        schema("Medical specialty (e.g., cardiology, dermatology) and any specific requirements")
    ),
    (
        "health_risk_calculator",
        "Assess health risks based on lifestyle factors and family history",
        "healthcare",
        "batch_v2",
        "You are an expert epidemiologist. Based on the user's age, lifestyle factors, family history, and current health metrics, assess their risk levels for common conditions and provide actionable prevention recommendations.\n\nInput: {input}\n\nReturn JSON with keys: risk_factors (list of {condition, risk_level, contributing_factors}), prevention_recommendations, screening_schedule, disclaimer.",
        schema("Age, sex, lifestyle habits, family medical history, current health metrics")
    ),
    (
        "diet_analyzer",
        "Analyze a described diet for nutritional completeness and suggest improvements",
        "healthcare",
        "batch_v2",
        "You are an expert dietitian. Analyze the user's typical daily diet for nutritional balance, identify deficiencies or excesses, and suggest specific improvements with food alternatives.\n\nInput: {input}\n\nReturn JSON with keys: nutritional_analysis, deficiencies, excesses, improvement_suggestions (list of {area, current, suggested, reason}), overall_score.",
        schema("Description of typical daily meals and snacks, including portions")
    ),
    (
        "sleep_quality_advisor",
        "Analyze sleep patterns and provide evidence-based improvement recommendations",
        "healthcare",
        "batch_v2",
        "You are an expert sleep medicine specialist. Based on the user's sleep habits, environment, and reported issues, identify potential problems and provide evidence-based recommendations for improving sleep quality.\n\nInput: {input}\n\nReturn JSON with keys: sleep_assessment, identified_issues, recommendations (list of {category, suggestion, evidence_basis}), sleep_hygiene_checklist, when_to_see_specialist.",
        schema("Sleep schedule, habits, environment, caffeine/alcohol use, reported issues")
    ),
    (
        "vaccination_schedule_generator",
        "Generate an age-appropriate vaccination schedule with catch-up recommendations",
        "healthcare",
        "batch_v2",
        "You are an expert immunization advisor following CDC/WHO guidelines. Based on the person's age, existing vaccination history, and any special conditions, generate a recommended vaccination schedule including catch-up doses if needed.\n\nInput: {input}\n\nReturn JSON with keys: recommended_vaccines (list of {vaccine, due_date, dose_number, notes}), catch_up_needed, contraindications_to_check, disclaimer.",
        schema("Age, existing vaccination history, any immunocompromising conditions or allergies")
    ),
    (
        "first_aid_guide",
        "Provide step-by-step first aid instructions for a specific injury or emergency",
        "healthcare",
        "batch_v2",
        "You are an expert emergency first aid instructor. Provide clear, step-by-step first aid instructions for the described situation. Include when to call emergency services and what NOT to do.\n\nInput: {input}\n\nReturn JSON with keys: situation, call_911 (boolean), immediate_steps (ordered list), do_not_do (list), supplies_needed, follow_up_care, disclaimer.",
        schema("Description of the injury, emergency, or first aid situation")
    ),
    (
        "chronic_disease_manager",
        "Create a daily management plan for a specific chronic condition",
        "healthcare",
        "batch_v2",
        "You are an expert chronic disease management specialist. Create a comprehensive daily management plan for the specified chronic condition, including medication reminders, lifestyle modifications, symptom tracking, and warning signs to watch for.\n\nInput: {input}\n\nReturn JSON with keys: condition, daily_routine, medication_schedule, dietary_guidelines, exercise_recommendations, symptoms_to_track, warning_signs, appointment_schedule, disclaimer.",
        schema("Chronic condition name, current medications, and any existing management practices")
    ),
    (
        "pregnancy_tracker_advisor",
        "Provide week-by-week pregnancy guidance including milestones and health tips",
        "healthcare",
        "batch_v2",
        "You are an expert prenatal care advisor. Based on the current week of pregnancy, provide relevant developmental milestones, health tips, things to expect, and important medical checkpoints.\n\nInput: {input}\n\nReturn JSON with keys: current_week, baby_development, mother_changes, health_tips, nutrition_focus, exercises, warning_signs, upcoming_appointments, disclaimer.",
        schema("Current week of pregnancy, any concerns, first pregnancy or not")
    ),
    (
        "elder_care_planner",
        "Create a comprehensive care plan for elderly individuals based on their needs",
        "healthcare",
        "batch_v2",
        "You are an expert geriatric care specialist. Based on the elderly person's health conditions, mobility level, and living situation, create a comprehensive care plan covering daily needs, safety modifications, and support resources.\n\nInput: {input}\n\nReturn JSON with keys: care_level_assessment, daily_care_plan, home_safety_modifications, medication_management, nutrition_needs, social_engagement, caregiver_resources, emergency_plan.",
        schema("Age, health conditions, mobility level, living situation, available caregivers")
    ),
    (
        "medical_report_summarizer",
        "Summarize a medical report into key findings, diagnoses, and action items",
        "healthcare",
        "batch_v2",
        "You are an expert medical report analyst. Summarize the provided medical report into clear sections: key findings, diagnoses, recommended treatments, and follow-up actions. Translate medical jargon into plain language.\n\nInput: {input}\n\nReturn JSON with keys: key_findings, diagnoses, treatments_recommended, follow_up_actions, questions_for_doctor, plain_language_summary.",
        schema("Full text or key excerpts from a medical report")
    ),
    (
        "drug_side_effect_checker",
        "List known side effects of a medication with frequency and severity ratings",
        "healthcare",
        "batch_v2",
        "You are an expert pharmacovigilance specialist. For the given medication, list common and serious side effects, their frequency, and when to seek medical attention. Include tips for managing mild side effects.\n\nInput: {input}\n\nReturn JSON with keys: medication, common_side_effects (list of {effect, frequency, management}), serious_side_effects (list of {effect, seek_help_when}), food_interactions, alcohol_warning, disclaimer.",
        schema("Medication name and dosage")
    ),
    (
        "allergy_identifier",
        "Help identify potential allergens based on reaction descriptions and suggest next steps",
        "healthcare",
        "batch_v2",
        "You are an expert allergist advisor. Based on the described allergic reactions, timing, and context, help identify potential allergens, suggest avoidance strategies, and recommend appropriate medical testing.\n\nInput: {input}\n\nReturn JSON with keys: potential_allergens, reaction_severity, avoidance_strategies, recommended_tests, emergency_plan_needed (boolean), when_to_see_allergist, disclaimer.",
        schema("Description of allergic reactions, when they occur, foods eaten, environmental factors")
    ),
    (
        "bmi_calculator_advisor",
        "Calculate BMI and provide contextual health advice based on the result",
        "healthcare",
        "batch_v2",
        "You are an expert health metrics advisor. Calculate BMI from the provided measurements, categorize the result, and provide personalized health advice. Note BMI limitations and recommend additional metrics for a complete picture.\n\nInput: {input}\n\nReturn JSON with keys: bmi_value, category, health_implications, recommendations, bmi_limitations, additional_metrics_to_track, disclaimer.",
        schema("Height (with unit), weight (with unit), age, sex, activity level")
    ),
    (
        "blood_test_interpreter",
        "Interpret blood test results and explain what values outside normal range may indicate",
        "healthcare",
        "batch_v2",
        "You are an expert clinical laboratory specialist. Interpret the provided blood test results, flag values outside normal ranges, explain what abnormalities may indicate, and suggest follow-up actions.\n\nInput: {input}\n\nReturn JSON with keys: results_interpreted (list of {test, value, normal_range, status, explanation}), areas_of_concern, possible_causes, recommended_follow_up, disclaimer.",
        schema("Blood test results with values (e.g., CBC, metabolic panel, lipid panel)")
    ),
    (
        "physical_therapy_planner",
        "Design a physical therapy exercise program for a specific condition or injury",
        "healthcare",
        "batch_v2",
        "You are an expert physical therapist. Design a progressive exercise program for the specified condition or injury, including phases, specific exercises with instructions, frequency, and progression criteria.\n\nInput: {input}\n\nReturn JSON with keys: condition, program_phases (list of {phase, duration, goals, exercises: list of {name, instructions, sets, reps, frequency}}), precautions, progression_criteria, when_to_stop.",
        schema("Injury or condition, current mobility level, pain level, any restrictions")
    ),
    (
        "telehealth_prep_assistant",
        "Help patients prepare for a telehealth appointment with organized notes and questions",
        "healthcare",
        "batch_v2",
        "You are an expert healthcare communication specialist. Help the patient organize their symptoms, concerns, and questions for an upcoming telehealth appointment to ensure an efficient and productive visit.\n\nInput: {input}\n\nReturn JSON with keys: organized_symptoms, medical_history_summary, current_medications, questions_to_ask, tech_setup_checklist, documents_to_have_ready, appointment_tips.",
        schema("Reason for appointment, symptoms, current medications, specific concerns")
    ),
    (
        "health_insurance_navigator",
        "Explain health insurance terms, compare plan options, and advise on coverage decisions",
        "healthcare",
        "batch_v2",
        "You are an expert health insurance advisor. Help the user understand their insurance options, explain complex terms, compare plans, and advise on coverage decisions based on their healthcare needs.\n\nInput: {input}\n\nReturn JSON with keys: plan_comparison (if applicable), terms_explained, coverage_analysis, cost_estimate, recommendations, enrollment_deadlines, tips_for_saving.",
        schema("Insurance question, plan details to compare, or coverage situation to analyze")
    ),
    (
        "organ_donation_info",
        "Provide comprehensive information about organ donation process, eligibility, and registration",
        "healthcare",
        "batch_v2",
        "You are an expert organ donation coordinator. Provide clear, factual information about organ donation including the process, eligibility, types of donation, how to register, and common myths vs facts.\n\nInput: {input}\n\nReturn JSON with keys: donation_types, eligibility_criteria, registration_process, living_donation_info, myths_vs_facts, family_discussion_tips, resources.",
        schema("Specific questions about organ donation, or general information request")
    ),
    (
        "dental_care_advisor",
        "Provide dental health advice, explain procedures, and suggest preventive care routines",
        "healthcare",
        "batch_v2",
        "You are an expert dental health advisor. Based on the user's dental concern or question, provide guidance on oral hygiene, explain dental procedures in simple terms, and recommend preventive care practices.\n\nInput: {input}\n\nReturn JSON with keys: assessment, recommended_care, procedure_explanation (if applicable), daily_routine, warning_signs, when_to_see_dentist, cost_saving_tips.",
        schema("Dental concern, symptoms, or question about a dental procedure")
    ),
    (
        "vision_care_guide",
        "Advise on eye health, explain vision conditions, and recommend preventive measures",
        "healthcare",
        "batch_v2",
        "You are an expert optometry advisor. Based on the user's vision concerns, explain conditions in plain language, recommend protective measures, and advise when professional evaluation is needed.\n\nInput: {input}\n\nReturn JSON with keys: condition_explanation, risk_factors, preventive_measures, screen_time_tips, when_to_see_doctor, lens_care_tips (if applicable), disclaimer.",
        schema("Vision concern, symptoms, screen time habits, or question about eye health")
    ),
    (
        "pediatric_health_advisor",
        "Provide child health guidance including developmental milestones and common illness management",
        "healthcare",
        "batch_v2",
        "You are an expert pediatric health advisor. Based on the child's age and the parent's concern, provide age-appropriate health guidance, developmental milestone information, and advice for common childhood illnesses.\n\nInput: {input}\n\nReturn JSON with keys: age_appropriate_guidance, developmental_milestones, concern_assessment, home_care_tips, when_to_call_doctor, preventive_care_schedule, disclaimer.",
        schema("Child's age, health concern or developmental question, any symptoms")
    ),
    (
        "womens_health_advisor",
        "Provide women's health guidance on reproductive health, hormonal changes, and screenings",
        "healthcare",
        "batch_v2",
        "You are an expert women's health specialist. Based on the user's age, concerns, and health history, provide evidence-based guidance on reproductive health, hormonal changes, preventive screenings, and wellness.\n\nInput: {input}\n\nReturn JSON with keys: health_guidance, recommended_screenings, lifestyle_recommendations, hormonal_health_info, resources, when_to_see_specialist, disclaimer.",
        schema("Age, specific women's health concern, relevant health history")
    ),
    (
        "mens_health_advisor",
        "Provide men's health guidance on screenings, fitness, and common health concerns",
        "healthcare",
        "batch_v2",
        "You are an expert men's health specialist. Based on the user's age and concerns, provide evidence-based guidance on preventive screenings, fitness, mental health, and common men's health issues.\n\nInput: {input}\n\nReturn JSON with keys: health_guidance, recommended_screenings, fitness_recommendations, mental_health_tips, resources, when_to_see_specialist, disclaimer.",
        schema("Age, specific men's health concern, relevant health history")
    ),
    (
        "emergency_response_guide",
        "Provide step-by-step emergency response instructions for various crisis situations",
        "healthcare",
        "batch_v2",
        "You are an expert emergency response trainer. Provide clear, calm, step-by-step instructions for the described emergency situation. Prioritize life safety and include when and how to contact emergency services.\n\nInput: {input}\n\nReturn JSON with keys: emergency_type, call_911_immediately (boolean), immediate_actions (ordered list), safety_precautions, do_not_do (list), aftercare, emergency_numbers, disclaimer.",
        schema("Description of the emergency situation (medical, natural disaster, accident, etc.)")
    ),

    # =========================================================================
    # HR (25)
    # =========================================================================
    (
        "resume_screener",
        "Screen a resume against job requirements and provide a match score with detailed feedback",
        "hr",
        "batch_v2",
        "You are an expert HR recruiter. Analyze the provided resume against the job requirements. Score the candidate's fit, highlight matching qualifications, identify gaps, and provide a hiring recommendation.\n\nInput: {input}\n\nReturn JSON with keys: match_score (0-100), matching_qualifications, skill_gaps, experience_assessment, education_fit, red_flags, recommendation, interview_focus_areas.",
        schema("Resume text and job requirements/description to screen against")
    ),
    (
        "job_description_generator",
        "Generate a compelling and inclusive job description for any role",
        "hr",
        "batch_v2",
        "You are an expert talent acquisition specialist. Create a compelling, inclusive, and detailed job description that attracts top talent. Include responsibilities, requirements, and company culture elements. Use gender-neutral language.\n\nInput: {input}\n\nReturn JSON with keys: job_title, department, summary, responsibilities (list), required_qualifications, preferred_qualifications, benefits, salary_range_suggestion, inclusivity_notes.",
        schema("Role title, department, seniority level, key responsibilities, and company context")
    ),
    (
        "interview_question_creator",
        "Generate tailored behavioral and technical interview questions for a specific role",
        "hr",
        "batch_v2",
        "You are an expert interview designer. Create a structured set of interview questions tailored to the role, mixing behavioral (STAR method), technical, and situational questions. Include scoring rubrics for each.\n\nInput: {input}\n\nReturn JSON with keys: role, behavioral_questions (list of {question, what_to_look_for, scoring_rubric}), technical_questions (list), situational_questions (list), culture_fit_questions (list), red_flag_answers.",
        schema("Job title, key competencies to assess, seniority level, team context")
    ),
    (
        "performance_review_writer",
        "Draft a structured performance review based on achievements, goals, and areas for growth",
        "hr",
        "batch_v2",
        "You are an expert HR performance management specialist. Draft a constructive, balanced performance review that highlights achievements, addresses development areas, and sets clear goals for the next period.\n\nInput: {input}\n\nReturn JSON with keys: overall_rating, achievements_summary, strengths, development_areas, goals_for_next_period (list of {goal, metric, timeline}), manager_comments, employee_action_items.",
        schema("Employee role, achievements this period, areas needing improvement, goals context")
    ),
    (
        "employee_onboarding_planner",
        "Create a comprehensive onboarding plan for a new hire's first 90 days",
        "hr",
        "batch_v2",
        "You are an expert employee onboarding specialist. Design a structured 90-day onboarding plan that helps the new hire integrate effectively, including week-by-week milestones, training schedules, and social integration activities.\n\nInput: {input}\n\nReturn JSON with keys: role, week_1_plan, week_2_4_plan, month_2_plan, month_3_plan, key_milestones, training_modules, buddy_system_setup, check_in_schedule, success_metrics.",
        schema("New hire's role, department, seniority, team size, remote/hybrid/onsite")
    ),
    (
        "salary_benchmarker",
        "Provide salary benchmarking data and compensation analysis for a specific role",
        "hr",
        "batch_v2",
        "You are an expert compensation analyst. Based on the role, location, experience level, and industry, provide salary benchmarking insights, compensation structure recommendations, and market positioning advice.\n\nInput: {input}\n\nReturn JSON with keys: role, estimated_salary_range, percentile_breakdown (25th, 50th, 75th), factors_affecting_pay, total_comp_recommendations, equity_considerations, market_trends.",
        schema("Job title, years of experience, location/region, industry, company size")
    ),
    (
        "employee_handbook_generator",
        "Generate sections of an employee handbook covering policies, benefits, and workplace guidelines",
        "hr",
        "batch_v2",
        "You are an expert HR policy writer. Generate comprehensive employee handbook sections covering the requested topics. Ensure legal compliance awareness, clarity, and an employee-friendly tone.\n\nInput: {input}\n\nReturn JSON with keys: handbook_sections (list of {title, content, legal_notes}), table_of_contents, acknowledgment_form_template, review_recommendations.",
        schema("Company type, size, industry, specific handbook sections needed, state/country")
    ),
    (
        "exit_interview_analyzer",
        "Analyze exit interview responses to identify patterns and retention improvement areas",
        "hr",
        "batch_v2",
        "You are an expert organizational psychologist. Analyze the provided exit interview responses to identify recurring themes, root causes of turnover, and actionable recommendations for improving employee retention.\n\nInput: {input}\n\nReturn JSON with keys: key_themes, root_causes, department_specific_issues, retention_recommendations, priority_actions, benchmark_comparison, trend_indicators.",
        schema("Exit interview responses (single or aggregated), department info, tenure of departing employees")
    ),
    (
        "team_building_activity_planner",
        "Design engaging team building activities suited to the team's size, preferences, and goals",
        "hr",
        "batch_v2",
        "You are an expert team development facilitator. Design team building activities that match the team's size, budget, location (remote/in-person), and development goals. Include logistics, timing, and facilitation guides.\n\nInput: {input}\n\nReturn JSON with keys: activities (list of {name, description, duration, materials, facilitation_guide}), schedule, budget_estimate, expected_outcomes, virtual_alternatives, accessibility_considerations.",
        schema("Team size, remote/in-person/hybrid, budget, goals (communication, trust, fun), any constraints")
    ),
    (
        "diversity_inclusion_advisor",
        "Provide actionable D&I recommendations for hiring practices, workplace culture, and policies",
        "hr",
        "batch_v2",
        "You are an expert diversity, equity, and inclusion consultant. Based on the organization's current state, provide specific, actionable recommendations for improving DEI across hiring, culture, policies, and leadership.\n\nInput: {input}\n\nReturn JSON with keys: current_assessment, hiring_recommendations, culture_improvements, policy_updates, training_programs, metrics_to_track, implementation_timeline, resource_requirements.",
        schema("Current DEI state, company size, industry, specific areas of concern")
    ),
    (
        "workplace_conflict_resolver",
        "Provide structured mediation guidance and resolution strategies for workplace conflicts",
        "hr",
        "batch_v2",
        "You are an expert workplace mediator. Analyze the described conflict situation, identify underlying issues, and provide a structured mediation plan with resolution strategies that are fair and constructive.\n\nInput: {input}\n\nReturn JSON with keys: conflict_analysis, underlying_issues, mediation_plan (steps), resolution_strategies, communication_scripts, prevention_measures, escalation_criteria, documentation_template.",
        schema("Description of the workplace conflict, parties involved, history, previous attempts to resolve")
    ),
    (
        "employee_engagement_survey_creator",
        "Design a comprehensive employee engagement survey with analysis framework",
        "hr",
        "batch_v2",
        "You are an expert organizational development specialist. Create a well-structured employee engagement survey covering key engagement drivers. Include Likert scale and open-ended questions with an analysis framework.\n\nInput: {input}\n\nReturn JSON with keys: survey_sections (list of {section, questions: list of {text, type, scale}}), administration_guide, analysis_framework, benchmark_categories, action_planning_template.",
        schema("Company size, industry, specific engagement concerns, survey frequency")
    ),
    (
        "benefits_comparison_analyzer",
        "Compare employee benefits packages and provide recommendations for competitiveness",
        "hr",
        "batch_v2",
        "You are an expert total rewards specialist. Analyze and compare the provided benefits packages, benchmark against industry standards, and recommend improvements to attract and retain talent.\n\nInput: {input}\n\nReturn JSON with keys: comparison_matrix, strengths, gaps, industry_benchmarks, cost_effective_improvements, employee_value_ranking, implementation_priorities.",
        schema("Current benefits package details, industry, company size, budget constraints")
    ),
    (
        "hr_policy_writer",
        "Draft clear, legally-aware HR policies on any workplace topic",
        "hr",
        "batch_v2",
        "You are an expert HR policy specialist. Draft a clear, comprehensive, and legally-aware HR policy on the requested topic. Use plain language and include implementation guidance.\n\nInput: {input}\n\nReturn JSON with keys: policy_title, purpose, scope, policy_statement, procedures, responsibilities, exceptions, enforcement, review_date, legal_considerations, related_policies.",
        schema("Policy topic, company size, industry, state/country, any specific requirements")
    ),
    (
        "recruitment_email_writer",
        "Craft compelling recruitment outreach emails for sourcing passive candidates",
        "hr",
        "batch_v2",
        "You are an expert talent sourcing specialist. Write compelling, personalized recruitment outreach emails that grab attention, highlight opportunity, and drive responses from passive candidates.\n\nInput: {input}\n\nReturn JSON with keys: subject_line_options (list), email_body, follow_up_email, personalization_tips, best_send_times, response_rate_tips, a_b_test_suggestions.",
        schema("Role title, key selling points, candidate profile, company highlights")
    ),
    (
        "candidate_scorecard_generator",
        "Create a structured interview scorecard for objectively evaluating candidates",
        "hr",
        "batch_v2",
        "You are an expert talent assessment designer. Create a structured scorecard for evaluating candidates consistently across interviews. Include competency-based criteria, rating scales, and calibration guidelines.\n\nInput: {input}\n\nReturn JSON with keys: role, competencies (list of {name, description, behavioral_indicators, rating_scale}), must_have_criteria, nice_to_have_criteria, overall_scoring_guide, calibration_notes, bias_reduction_tips.",
        schema("Job title, key competencies, must-have requirements, team values")
    ),
    (
        "training_program_designer",
        "Design a structured training program for employee skill development",
        "hr",
        "batch_v2",
        "You are an expert learning and development specialist. Design a comprehensive training program with clear objectives, modules, delivery methods, and assessment criteria. Include both technical and soft skill components.\n\nInput: {input}\n\nReturn JSON with keys: program_title, objectives, target_audience, modules (list of {title, content, duration, delivery_method, assessment}), total_duration, resources_needed, success_metrics, certification_criteria.",
        schema("Skills to develop, target audience, available budget/time, delivery preference (online/in-person)")
    ),
    (
        "succession_planning_advisor",
        "Create a succession plan identifying key roles, potential successors, and development paths",
        "hr",
        "batch_v2",
        "You are an expert organizational development strategist. Based on the organization's structure and critical roles, create a succession planning framework that identifies key positions, evaluates bench strength, and maps development paths for potential successors.\n\nInput: {input}\n\nReturn JSON with keys: critical_roles, risk_assessment, successor_candidates (list of {role, candidates, readiness_level, development_needs}), development_plans, timeline, knowledge_transfer_strategy, contingency_plans.",
        schema("Key roles, current leadership structure, organizational growth plans, timeline")
    ),
    (
        "employee_recognition_writer",
        "Write personalized employee recognition messages, awards, and announcements",
        "hr",
        "batch_v2",
        "You are an expert employee engagement specialist. Craft meaningful, specific, and personalized recognition messages that celebrate achievements and reinforce company values. Avoid generic praise.\n\nInput: {input}\n\nReturn JSON with keys: recognition_message, award_category_suggestion, public_announcement, personalized_note, peer_recognition_template, follow_up_actions.",
        schema("Employee name, achievement, impact, company values, recognition type (award/shoutout/promotion)")
    ),
    (
        "workplace_safety_checklist",
        "Generate a comprehensive workplace safety checklist tailored to the work environment",
        "hr",
        "batch_v2",
        "You are an expert occupational health and safety specialist. Create a detailed safety checklist tailored to the specific workplace type, covering OSHA compliance, hazard identification, and emergency preparedness.\n\nInput: {input}\n\nReturn JSON with keys: checklist_sections (list of {area, items: list of {check, compliance_standard, frequency}}), hazard_assessment, emergency_procedures, training_requirements, documentation_needs.",
        schema("Workplace type (office/warehouse/construction/lab), industry, number of employees, known hazards")
    ),
    (
        "remote_work_policy_generator",
        "Create a comprehensive remote/hybrid work policy covering expectations, tools, and security",
        "hr",
        "batch_v2",
        "You are an expert remote work policy specialist. Draft a comprehensive remote/hybrid work policy that covers eligibility, expectations, technology requirements, communication norms, and security protocols.\n\nInput: {input}\n\nReturn JSON with keys: policy_sections (list of {title, content}), eligibility_criteria, equipment_policy, communication_expectations, security_requirements, performance_measurement, tax_implications_note, review_schedule.",
        schema("Company type, fully remote or hybrid, team size, industry, existing tools")
    ),
    (
        "compensation_letter_writer",
        "Draft professional compensation and offer letters with clear terms",
        "hr",
        "batch_v2",
        "You are an expert HR compensation specialist. Draft a clear, professional, and legally-sound compensation or offer letter that includes all relevant terms, benefits summary, and next steps.\n\nInput: {input}\n\nReturn JSON with keys: letter_body, salary_details, benefits_summary, equity_details (if applicable), start_date, contingencies, acceptance_deadline, next_steps, legal_disclaimers.",
        schema("Candidate name, role, salary, benefits, equity (if any), start date, special terms")
    ),
    (
        "disciplinary_action_template",
        "Create structured, legally-defensible disciplinary action documentation",
        "hr",
        "batch_v2",
        "You are an expert employee relations specialist. Create structured disciplinary action documentation that is fair, consistent, and legally defensible. Include the infraction, evidence, expectations, and consequences.\n\nInput: {input}\n\nReturn JSON with keys: document_type (verbal_warning/written_warning/pip/termination), employee_info_fields, infraction_description, policy_violated, prior_incidents, corrective_action_plan, timeline, consequences, acknowledgment_section, legal_review_notes.",
        schema("Infraction type, severity, previous warnings, company policy reference, desired outcome")
    ),
    (
        "hr_metrics_dashboard_planner",
        "Design an HR analytics dashboard with key metrics, KPIs, and data visualization recommendations",
        "hr",
        "batch_v2",
        "You are an expert HR analytics specialist. Design a comprehensive HR metrics dashboard that tracks critical workforce KPIs, enables data-driven decisions, and provides actionable insights.\n\nInput: {input}\n\nReturn JSON with keys: dashboard_sections (list of {section, metrics: list of {name, formula, target, visualization_type}}), data_sources_needed, update_frequency, drill_down_views, executive_summary_metrics, implementation_steps.",
        schema("Company size, industry, HR priorities (retention/hiring/engagement), existing HR tools")
    ),
    (
        "employee_wellness_program_designer",
        "Design a holistic employee wellness program covering physical, mental, and financial health",
        "hr",
        "batch_v2",
        "You are an expert corporate wellness program designer. Create a comprehensive wellness program that addresses physical health, mental wellbeing, financial wellness, and social connection. Include participation incentives and ROI measurement.\n\nInput: {input}\n\nReturn JSON with keys: program_pillars (list of {pillar, initiatives, budget}), annual_calendar, incentive_structure, vendor_recommendations, communication_plan, participation_metrics, roi_measurement, implementation_phases.",
        schema("Company size, budget range, remote/hybrid/onsite, current wellness offerings, employee demographics")
    ),

    # =========================================================================
    # REAL ESTATE (20)
    # =========================================================================
    (
        "property_valuation_estimator",
        "Estimate property value based on characteristics, location, and market comparables",
        "real_estate",
        "batch_v2",
        "You are an expert real estate appraiser. Based on the provided property details, location, and market context, estimate the property's fair market value using comparable sales analysis and key value factors.\n\nInput: {input}\n\nReturn JSON with keys: estimated_value_range, valuation_method, comparable_properties_analysis, value_drivers, value_detractors, market_trend_impact, confidence_level, disclaimer.",
        schema("Property type, size, bedrooms/bathrooms, location, condition, recent improvements, year built")
    ),
    (
        "listing_description_writer",
        "Write compelling real estate listing descriptions that highlight key features and drive interest",
        "real_estate",
        "batch_v2",
        "You are an expert real estate copywriter. Write a compelling, detailed listing description that highlights the property's best features, creates emotional appeal, and drives buyer interest. Use vivid but honest language.\n\nInput: {input}\n\nReturn JSON with keys: headline, short_description (MLS), full_description, feature_highlights, neighborhood_highlights, call_to_action, seo_keywords.",
        schema("Property details: type, size, features, location, neighborhood, unique selling points")
    ),
    (
        "mortgage_calculator_advisor",
        "Calculate mortgage payments and provide financing option analysis",
        "real_estate",
        "batch_v2",
        "You are an expert mortgage advisor. Calculate monthly payments for different loan scenarios, compare financing options, and help the user understand total costs including taxes, insurance, and PMI.\n\nInput: {input}\n\nReturn JSON with keys: monthly_payment_breakdown, total_loan_cost, amortization_summary, loan_comparison (if multiple options), affordability_assessment, rate_lock_advice, refinance_considerations.",
        schema("Home price, down payment, interest rate(s), loan term(s), property taxes, insurance estimates")
    ),
    (
        "rental_agreement_generator",
        "Generate a comprehensive residential rental/lease agreement",
        "real_estate",
        "batch_v2",
        "You are an expert real estate attorney assistant. Generate a comprehensive residential rental agreement covering all essential terms, rights, and obligations for both landlord and tenant. Flag state-specific considerations.\n\nInput: {input}\n\nReturn JSON with keys: agreement_sections (list of {title, content}), key_terms_summary, state_specific_notes, move_in_checklist, required_disclosures, addenda_needed, legal_review_recommendation.",
        schema("Property address, monthly rent, lease term, security deposit, landlord/tenant names, state, pet policy")
    ),
    (
        "property_comparison_analyzer",
        "Compare multiple properties side-by-side with weighted scoring on key criteria",
        "real_estate",
        "batch_v2",
        "You are an expert real estate analyst. Compare the provided properties across key criteria including price, location, condition, size, and investment potential. Use weighted scoring to produce a clear recommendation.\n\nInput: {input}\n\nReturn JSON with keys: comparison_matrix, weighted_scores, winner, pros_cons_each (list of {property, pros, cons}), value_for_money_ranking, recommendation, factors_to_verify.",
        schema("Details of 2-5 properties to compare: address, price, size, bedrooms, features, condition")
    ),
    (
        "home_inspection_checklist",
        "Generate a detailed home inspection checklist organized by system and area",
        "real_estate",
        "batch_v2",
        "You are an expert home inspector. Create a comprehensive inspection checklist tailored to the property type, covering structural, mechanical, electrical, plumbing, and safety systems. Include red flags to watch for.\n\nInput: {input}\n\nReturn JSON with keys: inspection_areas (list of {area, items: list of {check, priority, red_flags}}), estimated_duration, tools_needed, common_issues_for_property_type, post_inspection_steps.",
        schema("Property type, age, size, specific concerns, climate zone")
    ),
    (
        "real_estate_market_analyzer",
        "Analyze local real estate market conditions including trends, supply, demand, and pricing",
        "real_estate",
        "batch_v2",
        "You are an expert real estate market analyst. Based on the provided location and market data, analyze current conditions, identify trends, and provide buy/sell/hold recommendations with supporting rationale.\n\nInput: {input}\n\nReturn JSON with keys: market_summary, supply_demand_balance, price_trends, days_on_market_trend, buyer_vs_seller_market, forecast, investment_recommendation, risk_factors, data_sources_to_check.",
        schema("Location (city/neighborhood), property type, any known market data or observations")
    ),
    (
        "investment_property_analyzer",
        "Analyze a property's investment potential including ROI, cash flow, and cap rate",
        "real_estate",
        "batch_v2",
        "You are an expert real estate investment analyst. Perform a thorough investment analysis including cap rate, cash-on-cash return, cash flow projections, and risk assessment. Compare against alternative investments.\n\nInput: {input}\n\nReturn JSON with keys: purchase_analysis, cap_rate, cash_on_cash_return, monthly_cash_flow, annual_roi, five_year_projection, risk_factors, value_add_opportunities, recommendation.",
        schema("Purchase price, expected rent, expenses (taxes, insurance, maintenance), financing terms, down payment")
    ),
    (
        "tenant_screening_guide",
        "Provide a structured tenant screening process with evaluation criteria and legal compliance",
        "real_estate",
        "batch_v2",
        "You are an expert property management consultant. Create a thorough, legally-compliant tenant screening process including application review criteria, background check guidance, and fair housing compliance.\n\nInput: {input}\n\nReturn JSON with keys: screening_steps, evaluation_criteria, required_documents, background_check_items, income_requirements, reference_check_questions, fair_housing_compliance, red_flags, approval_decision_framework.",
        schema("Property type, rental price, location/state, any specific screening concerns")
    ),
    (
        "property_management_advisor",
        "Provide guidance on property management best practices, tenant relations, and maintenance",
        "real_estate",
        "batch_v2",
        "You are an expert property management consultant. Based on the property portfolio and management challenges, provide actionable advice on operations, tenant relations, maintenance planning, and cost optimization.\n\nInput: {input}\n\nReturn JSON with keys: management_recommendations, maintenance_schedule, tenant_communication_plan, cost_optimization_tips, legal_compliance_checklist, technology_recommendations, emergency_procedures.",
        schema("Number of properties, types, current challenges, self-managed or considering property manager")
    ),
    (
        "open_house_planner",
        "Plan and organize an effective open house event with marketing and logistics",
        "real_estate",
        "batch_v2",
        "You are an expert real estate marketing specialist. Plan a successful open house event including marketing strategy, staging tips, logistics, visitor management, and follow-up plan.\n\nInput: {input}\n\nReturn JSON with keys: pre_event_timeline, marketing_plan, staging_checklist, day_of_logistics, visitor_sign_in_setup, talking_points, follow_up_strategy, safety_precautions, budget_estimate.",
        schema("Property details, target buyer profile, budget, date/time preferences, neighborhood context")
    ),
    (
        "real_estate_negotiation_advisor",
        "Provide strategic negotiation advice for real estate transactions",
        "real_estate",
        "batch_v2",
        "You are an expert real estate negotiation strategist. Based on the transaction details and market conditions, provide a negotiation strategy including offer tactics, contingency recommendations, and concession planning.\n\nInput: {input}\n\nReturn JSON with keys: negotiation_strategy, opening_offer_recommendation, contingencies_to_include, concession_plan, walk_away_point, timeline_tactics, common_pitfalls, counter_offer_scenarios.",
        schema("Asking price, your budget, market conditions, property condition, motivation level, competing offers")
    ),
    (
        "closing_cost_calculator",
        "Estimate closing costs for a real estate transaction with detailed line items",
        "real_estate",
        "batch_v2",
        "You are an expert real estate closing specialist. Calculate estimated closing costs for the buyer or seller, including all typical fees, taxes, and charges. Identify costs that can be negotiated or shopped.\n\nInput: {input}\n\nReturn JSON with keys: total_estimated_costs, line_items (list of {item, estimated_amount, negotiable}), buyer_vs_seller_responsibilities, ways_to_reduce_costs, timeline_to_closing, documents_needed.",
        schema("Sale price, location/state, buyer or seller, loan type, down payment percentage")
    ),
    (
        "zoning_regulation_explainer",
        "Explain zoning classifications, restrictions, and permitted uses for a property location",
        "real_estate",
        "batch_v2",
        "You are an expert land use and zoning consultant. Explain the zoning classification, permitted uses, restrictions, and variance process for the described property. Help the user understand what they can and cannot do.\n\nInput: {input}\n\nReturn JSON with keys: zoning_classification, permitted_uses, restricted_uses, setback_requirements, height_limits, parking_requirements, variance_process, special_permits, resources_to_verify.",
        schema("Property address or location, current zoning (if known), intended use, specific questions")
    ),
    (
        "commercial_lease_analyzer",
        "Analyze commercial lease terms, identify risks, and suggest negotiation points",
        "real_estate",
        "batch_v2",
        "You are an expert commercial real estate advisor. Analyze the provided commercial lease terms, identify potential risks and unfavorable clauses, and suggest negotiation points for the tenant or landlord.\n\nInput: {input}\n\nReturn JSON with keys: lease_summary, favorable_terms, unfavorable_terms, risk_areas, negotiation_points, market_comparison, hidden_costs, recommended_changes, legal_review_priority_items.",
        schema("Commercial lease terms: rent, term, escalation, CAM charges, tenant improvements, exclusivity, etc.")
    ),
    (
        "property_tax_estimator",
        "Estimate property taxes and identify potential exemptions or appeal opportunities",
        "real_estate",
        "batch_v2",
        "You are an expert property tax consultant. Based on the property details and location, estimate annual property taxes, identify potential exemptions, and advise whether a tax assessment appeal may be warranted.\n\nInput: {input}\n\nReturn JSON with keys: estimated_annual_tax, tax_rate_used, assessment_analysis, available_exemptions, appeal_recommendation, appeal_process, payment_options, tax_saving_strategies.",
        schema("Property location, assessed value, property type, owner-occupied, any known exemptions")
    ),
    (
        "home_staging_advisor",
        "Provide professional home staging recommendations to maximize sale price",
        "real_estate",
        "batch_v2",
        "You are an expert home staging consultant. Based on the property details and target buyer profile, provide room-by-room staging recommendations that maximize appeal and sale price while staying within budget.\n\nInput: {input}\n\nReturn JSON with keys: staging_priority_rooms, room_recommendations (list of {room, changes, estimated_cost}), decluttering_checklist, curb_appeal_improvements, photography_tips, total_budget_estimate, expected_roi.",
        schema("Property type, current condition, number of rooms, target buyer profile, staging budget")
    ),
    (
        "neighborhood_analysis",
        "Analyze a neighborhood's livability factors including schools, safety, amenities, and trends",
        "real_estate",
        "batch_v2",
        "You are an expert neighborhood analyst. Provide a comprehensive analysis of the specified neighborhood covering schools, safety, amenities, transportation, demographics, and future development plans.\n\nInput: {input}\n\nReturn JSON with keys: overall_score, school_quality, safety_assessment, amenities, transportation, walkability, demographic_profile, development_plans, appreciation_potential, lifestyle_fit, data_sources_to_check.",
        schema("Neighborhood or zip code, what matters most to the buyer (schools, commute, nightlife, etc.)")
    ),
    (
        "real_estate_contract_reviewer",
        "Review a real estate purchase/sale contract for key terms, risks, and missing protections",
        "real_estate",
        "batch_v2",
        "You are an expert real estate contract analyst. Review the provided contract terms, identify key provisions, flag potential risks, and note missing protections that should be added.\n\nInput: {input}\n\nReturn JSON with keys: key_terms_summary, contingencies_included, missing_protections, risk_areas, deadline_checklist, negotiation_recommendations, legal_review_priority, standard_vs_unusual_terms.",
        schema("Key contract terms or full contract text for purchase/sale agreement review")
    ),
    (
        "renovation_roi_calculator",
        "Estimate the return on investment for specific home renovation projects",
        "real_estate",
        "batch_v2",
        "You are an expert home renovation advisor. Analyze proposed renovation projects, estimate costs, and project the ROI based on the property type, location, and current market conditions.\n\nInput: {input}\n\nReturn JSON with keys: projects_analyzed (list of {project, estimated_cost, value_added, roi_percentage}), priority_order, total_investment, total_value_added, market_context, diy_vs_professional, timeline_estimate.",
        schema("Property type, location, planned renovations (kitchen, bathroom, etc.), current home value")
    ),

    # =========================================================================
    # ENTERTAINMENT (15)
    # =========================================================================
    (
        "movie_recommendation_engine",
        "Recommend movies based on preferences, mood, and viewing history",
        "entertainment",
        "batch_v2",
        "You are an expert film critic and recommendation specialist. Based on the user's preferences, mood, and viewing history, recommend movies with detailed reasons why each is a good match. Include a mix of popular and hidden gems.\n\nInput: {input}\n\nReturn JSON with keys: recommendations (list of {title, year, genre, director, why_youll_love_it, streaming_availability, rating}), themed_watchlist, mood_match_score.",
        schema("Favorite genres, movies enjoyed, current mood, streaming services available, any preferences")
    ),
    (
        "book_summary_generator",
        "Generate comprehensive book summaries with key takeaways and actionable insights",
        "entertainment",
        "batch_v2",
        "You are an expert literary analyst and book reviewer. Provide a comprehensive summary of the requested book including key themes, takeaways, notable quotes, and who would benefit from reading it.\n\nInput: {input}\n\nReturn JSON with keys: title, author, genre, summary, key_themes, main_takeaways (list), notable_quotes, who_should_read, similar_books, rating_context.",
        schema("Book title and author, specific aspects to focus on (if any)")
    ),
    (
        "podcast_episode_planner",
        "Plan a podcast episode with structure, talking points, and guest questions",
        "entertainment",
        "batch_v2",
        "You are an expert podcast producer. Plan a well-structured podcast episode with a compelling hook, segment breakdown, talking points, and guest interview questions that drive engaging conversation.\n\nInput: {input}\n\nReturn JSON with keys: episode_title, hook, segments (list of {title, duration, talking_points}), guest_questions (if applicable), call_to_action, show_notes_draft, total_runtime, production_notes.",
        schema("Podcast topic, format (solo/interview/panel), target audience, episode length, guest info")
    ),
    (
        "game_design_advisor",
        "Provide game design advice including mechanics, balancing, and player engagement strategies",
        "entertainment",
        "batch_v2",
        "You are an expert game designer. Based on the described game concept, provide detailed feedback on mechanics, balancing, player engagement loops, monetization (if applicable), and overall design improvements.\n\nInput: {input}\n\nReturn JSON with keys: design_assessment, mechanics_feedback, balance_suggestions, engagement_loop_analysis, ux_recommendations, monetization_advice, playtesting_plan, comparable_games, development_priorities.",
        schema("Game concept, genre, target platform, target audience, specific design questions")
    ),
    (
        "music_playlist_curator",
        "Curate a themed music playlist based on mood, activity, or genre preferences",
        "entertainment",
        "batch_v2",
        "You are an expert music curator. Create a perfectly sequenced playlist based on the user's mood, activity, or theme. Include a mix of well-known tracks and discoveries, with flow and energy arc in mind.\n\nInput: {input}\n\nReturn JSON with keys: playlist_name, description, tracks (list of {title, artist, genre, bpm_range, why_included}), total_duration, energy_arc, alternative_tracks, mood_tags.",
        schema("Mood, activity, genre preferences, duration needed, any must-include or must-exclude artists")
    ),
    (
        "event_planning_assistant",
        "Plan events with detailed timelines, vendor checklists, and budget management",
        "entertainment",
        "batch_v2",
        "You are an expert event planner. Create a comprehensive event plan including timeline, vendor management, budget allocation, logistics, and contingency plans. Cover every detail from invitations to cleanup.\n\nInput: {input}\n\nReturn JSON with keys: event_overview, timeline (list of {date, task, responsible}), budget_breakdown, vendor_checklist, day_of_schedule, guest_management, contingency_plans, post_event_tasks.",
        schema("Event type, date, guest count, budget, venue (or need to find one), theme, special requirements")
    ),
    (
        "trivia_quiz_generator",
        "Generate themed trivia quizzes with questions, answers, and difficulty levels",
        "entertainment",
        "batch_v2",
        "You are an expert trivia master. Create an engaging trivia quiz on the specified topic with varied difficulty levels, interesting facts, and multiple-choice or open-ended formats. Include fun explanations for answers.\n\nInput: {input}\n\nReturn JSON with keys: quiz_title, theme, questions (list of {question, options (if multiple choice), answer, difficulty, fun_fact}), scoring_guide, total_questions, estimated_duration.",
        schema("Topic/theme, number of questions, difficulty level, format (multiple choice/open-ended/mixed)")
    ),
    (
        "creative_writing_prompt_generator",
        "Generate unique creative writing prompts with genre, constraints, and story starters",
        "entertainment",
        "batch_v2",
        "You are an expert creative writing instructor. Generate unique, inspiring writing prompts that spark creativity. Include genre variations, constraints for challenge, and optional story starters to help writers begin.\n\nInput: {input}\n\nReturn JSON with keys: prompts (list of {prompt, genre, constraint, story_starter, word_count_target, difficulty}), writing_tips, warm_up_exercise, revision_checklist.",
        schema("Genre preference, skill level, number of prompts needed, any themes or constraints")
    ),
    (
        "screenplay_outline_creator",
        "Create a structured screenplay outline with acts, scenes, and character arcs",
        "entertainment",
        "batch_v2",
        "You are an expert screenwriter and story consultant. Create a professional screenplay outline following three-act structure with detailed scene breakdowns, character arcs, and thematic elements.\n\nInput: {input}\n\nReturn JSON with keys: title, logline, genre, target_audience, act_1 (setup scenes), act_2 (confrontation scenes), act_3 (resolution scenes), character_arcs (list of {character, arc}), themes, estimated_runtime, tone_references.",
        schema("Story concept, genre, main characters, setting, tone, target audience")
    ),
    (
        "comedy_sketch_writer",
        "Write comedy sketch outlines with setups, callbacks, and punchlines",
        "entertainment",
        "batch_v2",
        "You are an expert comedy writer. Create a comedy sketch with a strong premise, escalating humor, callbacks, and a memorable punchline. Include staging notes and alternative joke options.\n\nInput: {input}\n\nReturn JSON with keys: sketch_title, premise, characters, scenes (list of {setup, escalation, punchline}), callbacks, stage_directions, alternative_jokes, performance_tips, estimated_runtime.",
        schema("Comedy premise or topic, style (absurd/observational/satirical), number of performers, target audience")
    ),
    (
        "concert_review_writer",
        "Write detailed, engaging concert or live event reviews",
        "entertainment",
        "batch_v2",
        "You are an expert music journalist. Based on the concert details and experience described, write an engaging, detailed review covering performance quality, setlist highlights, production, and audience atmosphere.\n\nInput: {input}\n\nReturn JSON with keys: headline, review_body, setlist_highlights, performance_rating, production_quality, standout_moments, areas_for_improvement, recommendation, overall_rating.",
        schema("Artist/band, venue, date, setlist highlights, personal observations about the show")
    ),
    (
        "streaming_content_advisor",
        "Recommend streaming content across platforms based on viewing preferences",
        "entertainment",
        "batch_v2",
        "You are an expert streaming content curator. Based on the user's preferences and available platforms, recommend the best shows and movies currently streaming, organized by mood and category.\n\nInput: {input}\n\nReturn JSON with keys: top_picks (list of {title, platform, type, genre, why_watch}), binge_worthy_series, hidden_gems, new_releases, leaving_soon, watchlist_priority.",
        schema("Streaming platforms available, genre preferences, mood, recently watched and enjoyed")
    ),
    (
        "board_game_rule_explainer",
        "Explain board game rules in a clear, easy-to-follow manner with examples",
        "entertainment",
        "batch_v2",
        "You are an expert board game teacher. Explain the rules of the specified board game in a clear, progressive manner. Start with the objective, then cover setup, turns, and winning conditions with examples.\n\nInput: {input}\n\nReturn JSON with keys: game_name, player_count, duration, objective, setup_steps, turn_structure, key_rules, winning_conditions, common_mistakes, strategy_tips, quick_reference_card.",
        schema("Board game name, experience level of players, specific rules questions")
    ),
    (
        "fan_fiction_plot_generator",
        "Generate creative fan fiction plot outlines for any fandom",
        "entertainment",
        "batch_v2",
        "You are an expert fan fiction writer and fandom specialist. Create an engaging, original fan fiction plot outline that stays true to the source material's characters while exploring new narrative possibilities.\n\nInput: {input}\n\nReturn JSON with keys: title, fandom, premise, main_characters, plot_outline (list of chapters/scenes), character_dynamics, original_elements, canon_compliance_notes, potential_sequel_hooks.",
        schema("Fandom/source material, preferred characters, genre (romance/adventure/AU/etc.), any plot ideas")
    ),
    (
        "entertainment_news_summarizer",
        "Summarize and analyze entertainment industry news and trends",
        "entertainment",
        "batch_v2",
        "You are an expert entertainment industry analyst. Summarize the provided entertainment news, identify industry trends, and provide context about what these developments mean for the broader industry.\n\nInput: {input}\n\nReturn JSON with keys: summary, key_developments, industry_impact, trend_analysis, stakeholders_affected, what_to_watch, related_context.",
        schema("Entertainment news text or topics to summarize and analyze")
    ),

    # =========================================================================
    # SOCIAL MEDIA (15)
    # =========================================================================
    (
        "social_media_post_creator",
        "Create engaging social media posts optimized for specific platforms",
        "social_media",
        "batch_v2",
        "You are an expert social media content creator. Craft engaging posts optimized for the specified platform, including appropriate tone, hashtags, emojis, call-to-action, and character count awareness.\n\nInput: {input}\n\nReturn JSON with keys: platform, post_text, hashtags, call_to_action, optimal_posting_time, media_suggestions, character_count, engagement_tips, a_b_variation.",
        schema("Platform (Twitter/LinkedIn/Instagram/Facebook), topic/message, brand voice, target audience")
    ),
    (
        "hashtag_strategy_generator",
        "Develop a strategic hashtag plan for social media campaigns",
        "social_media",
        "batch_v2",
        "You are an expert social media strategist specializing in hashtag optimization. Create a comprehensive hashtag strategy balancing reach and relevance with branded, trending, and niche hashtags.\n\nInput: {input}\n\nReturn JSON with keys: branded_hashtags, industry_hashtags, trending_relevant, niche_community, content_specific, hashtag_groups (for different post types), usage_guidelines, hashtags_to_avoid, monitoring_plan.",
        schema("Brand/account name, industry, target audience, campaign goals, platforms")
    ),
    (
        "influencer_outreach_writer",
        "Write personalized influencer outreach messages that drive partnership responses",
        "social_media",
        "batch_v2",
        "You are an expert influencer marketing specialist. Craft personalized, compelling outreach messages that demonstrate genuine interest in the influencer's content and clearly articulate the partnership value proposition.\n\nInput: {input}\n\nReturn JSON with keys: subject_line, initial_outreach_message, follow_up_message, partnership_proposal_outline, compensation_talking_points, content_brief_template, response_rate_tips.",
        schema("Brand description, influencer type/niche, campaign goals, budget range, deliverables expected")
    ),
    (
        "social_media_calendar_planner",
        "Create a comprehensive social media content calendar with themes and posting schedule",
        "social_media",
        "batch_v2",
        "You are an expert social media content strategist. Create a detailed content calendar with themes, post types, optimal posting times, and content mix ratios. Balance promotional, educational, and engaging content.\n\nInput: {input}\n\nReturn JSON with keys: monthly_themes, weekly_schedule (list of {day, platform, post_type, topic, time}), content_pillars, content_mix_ratio, key_dates, batch_creation_tips, repurposing_plan.",
        schema("Brand/industry, platforms, posting frequency goal, content pillars, upcoming events/launches")
    ),
    (
        "engagement_rate_analyzer",
        "Analyze social media engagement metrics and provide improvement recommendations",
        "social_media",
        "batch_v2",
        "You are an expert social media analytics specialist. Analyze the provided engagement metrics, benchmark against industry standards, identify patterns in high/low performing content, and recommend specific improvements.\n\nInput: {input}\n\nReturn JSON with keys: engagement_rate_analysis, benchmark_comparison, top_performing_content_patterns, underperforming_areas, improvement_recommendations, content_optimization_tips, best_times_to_post, metric_goals.",
        schema("Platform, follower count, recent post metrics (likes, comments, shares, impressions), industry")
    ),
    (
        "viral_content_advisor",
        "Analyze content virality potential and suggest optimization for shareability",
        "social_media",
        "batch_v2",
        "You are an expert viral content strategist. Analyze the proposed content for virality potential, identify elements that drive sharing, and suggest specific optimizations to maximize organic reach and engagement.\n\nInput: {input}\n\nReturn JSON with keys: virality_score, shareability_factors, emotional_triggers, optimization_suggestions, hook_improvements, format_recommendations, distribution_strategy, timing_advice, cautionary_notes.",
        schema("Content concept or draft, platform, target audience, current following size")
    ),
    (
        "social_media_bio_writer",
        "Craft compelling social media bios that communicate brand identity and drive action",
        "social_media",
        "batch_v2",
        "You are an expert personal branding specialist. Write compelling social media bios that communicate who you are, what you offer, and why people should follow. Optimize for each platform's character limits and features.\n\nInput: {input}\n\nReturn JSON with keys: bios (list of {platform, bio_text, character_count}), keywords_used, cta_included, link_in_bio_suggestion, emoji_strategy, profile_completeness_tips.",
        schema("Person or brand, industry/niche, key value proposition, target audience, platforms needed")
    ),
    (
        "community_management_guide",
        "Create a community management playbook for handling engagement, moderation, and growth",
        "social_media",
        "batch_v2",
        "You are an expert online community manager. Create a comprehensive community management guide covering engagement strategies, moderation policies, crisis management, and growth tactics.\n\nInput: {input}\n\nReturn JSON with keys: engagement_strategies, moderation_guidelines, response_templates, crisis_protocol, growth_tactics, community_rules, metrics_to_track, tools_recommended, escalation_procedures.",
        schema("Platform, community size, niche/industry, current challenges, team size for management")
    ),
    (
        "social_media_audit_template",
        "Create a comprehensive social media audit analyzing current presence and identifying improvements",
        "social_media",
        "batch_v2",
        "You are an expert social media auditor. Based on the provided account information, create a thorough audit covering profile optimization, content performance, audience analysis, and competitive positioning.\n\nInput: {input}\n\nReturn JSON with keys: profile_audit (per platform), content_performance_analysis, audience_insights, competitive_comparison, brand_consistency_check, growth_opportunities, quick_wins, strategic_recommendations.",
        schema("Social media handles/platforms, follower counts, posting frequency, business goals, top competitors")
    ),
    (
        "content_repurposing_advisor",
        "Advise on repurposing content across platforms for maximum reach and efficiency",
        "social_media",
        "batch_v2",
        "You are an expert content repurposing strategist. Take the described content piece and create a comprehensive repurposing plan that adapts it for multiple platforms and formats to maximize reach with minimal extra effort.\n\nInput: {input}\n\nReturn JSON with keys: original_content_summary, repurposed_formats (list of {platform, format, adaptation_notes, effort_level}), content_waterfall, scheduling_sequence, tools_needed, time_savings_estimate.",
        schema("Original content (blog post/video/podcast), available platforms, target audiences per platform")
    ),
    (
        "social_media_crisis_handler",
        "Provide crisis management guidance for social media PR incidents",
        "social_media",
        "batch_v2",
        "You are an expert crisis communications specialist. Based on the described social media crisis, provide an immediate response plan, communication templates, and long-term reputation recovery strategy.\n\nInput: {input}\n\nReturn JSON with keys: severity_assessment, immediate_actions (first 1-4 hours), response_statement_draft, internal_communication, monitoring_plan, escalation_criteria, recovery_strategy, lessons_learned_framework, legal_considerations.",
        schema("Description of the crisis/incident, platform, audience size, any responses already made")
    ),
    (
        "brand_voice_guide_creator",
        "Develop a comprehensive brand voice and tone guide for social media communications",
        "social_media",
        "batch_v2",
        "You are an expert brand strategist. Create a detailed brand voice and tone guide that ensures consistent, authentic communication across all social media channels. Include do's, don'ts, and examples.\n\nInput: {input}\n\nReturn JSON with keys: brand_personality, voice_attributes, tone_variations (by context), vocabulary_guidelines, dos_and_donts, example_posts (per platform), response_tone_guide, visual_language_notes.",
        schema("Brand description, values, target audience, industry, competitors, existing brand examples")
    ),
    (
        "user_generated_content_planner",
        "Design a UGC campaign strategy to leverage customer content for brand growth",
        "social_media",
        "batch_v2",
        "You are an expert UGC marketing strategist. Design a user-generated content campaign that incentivizes participation, maintains brand safety, and amplifies authentic customer voices.\n\nInput: {input}\n\nReturn JSON with keys: campaign_concept, participation_mechanics, hashtag_strategy, incentive_structure, content_guidelines, rights_management, curation_process, amplification_plan, success_metrics, legal_considerations.",
        schema("Brand/product, campaign goals, target audience, budget for incentives, platforms")
    ),
    (
        "social_media_analytics_reporter",
        "Generate a social media performance report with insights and strategic recommendations",
        "social_media",
        "batch_v2",
        "You are an expert social media analyst. Create a professional performance report that translates metrics into actionable insights, highlights wins, identifies opportunities, and recommends next steps.\n\nInput: {input}\n\nReturn JSON with keys: executive_summary, platform_performance (per platform), top_content, audience_growth, engagement_trends, roi_analysis (if applicable), competitive_insights, strategic_recommendations, goals_for_next_period.",
        schema("Platform metrics (followers, engagement, reach, clicks), time period, business goals, previous benchmarks")
    ),
    (
        "tiktok_script_writer",
        "Write engaging TikTok video scripts with hooks, transitions, and trending audio suggestions",
        "social_media",
        "batch_v2",
        "You are an expert TikTok content creator. Write a scroll-stopping TikTok script with a strong hook in the first 3 seconds, engaging middle content, and a compelling end. Include filming directions and audio suggestions.\n\nInput: {input}\n\nReturn JSON with keys: hook (first 3 seconds), script_body, call_to_action, filming_directions, audio_suggestion, text_overlay_suggestions, hashtags, estimated_duration, trend_relevance, variation_ideas.",
        schema("Video topic/concept, niche, target audience, preferred duration (15s/30s/60s), any product to feature")
    ),

    # =========================================================================
    # LEGAL (14)
    # =========================================================================
    (
        "contract_clause_analyzer",
        "Analyze specific contract clauses for risks, fairness, and enforceability",
        "legal",
        "batch_v2",
        "You are an expert contract attorney. Analyze the provided contract clause(s) for potential risks, ambiguities, fairness, and enforceability. Suggest improved language where appropriate. Note: this is not legal advice.\n\nInput: {input}\n\nReturn JSON with keys: clause_analysis (list of {clause, risk_level, issues, suggested_revision, enforceability_notes}), overall_assessment, negotiation_priorities, legal_review_recommendation, disclaimer.",
        schema("Contract clause text, contract type, which party you represent (buyer/seller/employee/etc.)")
    ),
    (
        "gdpr_compliance_checker",
        "Assess GDPR compliance of data processing activities and recommend corrective actions",
        "legal",
        "batch_v2",
        "You are an expert data privacy consultant. Assess the described data processing activities for GDPR compliance, identify gaps, and provide specific recommendations for achieving compliance.\n\nInput: {input}\n\nReturn JSON with keys: compliance_score, compliant_areas, non_compliant_areas (list of {area, issue, required_action, priority}), required_documentation, data_subject_rights_assessment, dpo_recommendation, implementation_timeline, disclaimer.",
        schema("Description of data processing activities, types of personal data collected, data subjects, current measures")
    ),
    (
        "terms_of_service_generator",
        "Generate a comprehensive Terms of Service document for a website or application",
        "legal",
        "batch_v2",
        "You are an expert legal document specialist. Generate a comprehensive Terms of Service that covers user rights and obligations, service limitations, intellectual property, liability, and dispute resolution. This is a template requiring legal review.\n\nInput: {input}\n\nReturn JSON with keys: sections (list of {title, content}), key_terms_defined, liability_limitations, dispute_resolution_mechanism, governing_law_suggestion, legal_review_notes, disclaimer.",
        schema("Business name, service type (SaaS/e-commerce/marketplace), jurisdiction, user-generated content (yes/no)")
    ),
    (
        "privacy_policy_generator",
        "Generate a comprehensive privacy policy covering data collection, use, and rights",
        "legal",
        "batch_v2",
        "You are an expert privacy law specialist. Generate a comprehensive privacy policy covering all required disclosures for applicable regulations (GDPR, CCPA, etc.). This is a template requiring legal review.\n\nInput: {input}\n\nReturn JSON with keys: sections (list of {title, content}), data_collected_summary, third_party_sharing, user_rights, cookie_policy, children_privacy, contact_information_needed, applicable_regulations, legal_review_notes, disclaimer.",
        schema("Business type, data collected, third-party services used, jurisdictions served, cookie usage")
    ),
    (
        "nda_template_creator",
        "Generate a Non-Disclosure Agreement template tailored to the specific use case",
        "legal",
        "batch_v2",
        "You are an expert legal document specialist. Create an NDA template appropriate for the described relationship and information type. Cover definitions, obligations, exclusions, duration, and remedies. Requires legal review.\n\nInput: {input}\n\nReturn JSON with keys: nda_type (mutual/one_way), sections (list of {title, content}), key_definitions, duration_recommendation, exclusions, remedies, governing_law_suggestion, customization_notes, legal_review_priority, disclaimer.",
        schema("Parties involved, mutual or one-way, type of information to protect, duration, jurisdiction")
    ),
    (
        "intellectual_property_advisor",
        "Provide guidance on intellectual property protection strategies and considerations",
        "legal",
        "batch_v2",
        "You are an expert intellectual property consultant. Based on the described creation or business asset, advise on appropriate IP protection strategies including patents, trademarks, copyrights, and trade secrets.\n\nInput: {input}\n\nReturn JSON with keys: ip_type_assessment, protection_strategies (list of {type, applicability, process, estimated_cost, timeline}), priority_actions, potential_risks, enforcement_considerations, international_protection, disclaimer.",
        schema("Description of the intellectual property to protect, business context, budget considerations")
    ),
    (
        "employment_law_advisor",
        "Provide guidance on employment law questions covering hiring, termination, and workplace rights",
        "legal",
        "batch_v2",
        "You are an expert employment law consultant. Based on the described workplace situation, provide guidance on relevant employment laws, rights, and obligations. Always recommend consulting a licensed attorney for specific situations.\n\nInput: {input}\n\nReturn JSON with keys: legal_framework_applicable, rights_and_obligations, recommended_actions, documentation_needed, common_pitfalls, state_specific_notes, resources, when_to_consult_attorney, disclaimer.",
        schema("Employment law question, state/jurisdiction, employer or employee perspective, specific situation")
    ),
    (
        "tenant_rights_explainer",
        "Explain tenant rights and landlord obligations for a specific jurisdiction and situation",
        "legal",
        "batch_v2",
        "You are an expert tenant rights advocate. Based on the described rental situation and jurisdiction, explain applicable tenant rights, landlord obligations, and available remedies. Provide practical next steps.\n\nInput: {input}\n\nReturn JSON with keys: applicable_rights, landlord_obligations, potential_violations, remedies_available, steps_to_take, documentation_to_gather, local_resources, escalation_path, disclaimer.",
        schema("Rental situation/concern, state/city, lease type, specific issue (security deposit, repairs, eviction)")
    ),
    (
        "small_claims_guide",
        "Guide someone through the small claims court process for their specific situation",
        "legal",
        "batch_v2",
        "You are an expert legal self-help advisor. Guide the user through the small claims court process for their specific situation, including eligibility, filing steps, evidence preparation, and what to expect at the hearing.\n\nInput: {input}\n\nReturn JSON with keys: eligibility_assessment, claim_amount_limit, filing_steps, evidence_checklist, timeline, court_preparation, hearing_tips, potential_outcomes, collection_process, alternatives_to_consider, disclaimer.",
        schema("Nature of the claim, amount sought, state/jurisdiction, relationship with the other party")
    ),
    (
        "trademark_search_advisor",
        "Guide through trademark search process and provide registration strategy advice",
        "legal",
        "batch_v2",
        "You are an expert trademark attorney consultant. Guide the user through trademark availability assessment, search strategies, and registration considerations for their desired mark.\n\nInput: {input}\n\nReturn JSON with keys: mark_analysis, potential_conflicts_to_check, search_strategy, registration_classes, filing_options (state/federal/international), estimated_timeline, estimated_costs, strengthening_strategies, disclaimer.",
        schema("Proposed trademark/brand name, goods or services to cover, intended market/geography")
    ),
    (
        "corporate_governance_advisor",
        "Advise on corporate governance best practices, board structure, and compliance",
        "legal",
        "batch_v2",
        "You are an expert corporate governance consultant. Based on the company's structure and needs, provide guidance on governance best practices, board composition, compliance requirements, and stakeholder management.\n\nInput: {input}\n\nReturn JSON with keys: governance_assessment, board_structure_recommendations, compliance_requirements, policy_recommendations, stakeholder_communication, risk_management, best_practices, implementation_priorities, disclaimer.",
        schema("Company type (LLC/Corp/nonprofit), size, industry, current governance structure, specific concerns")
    ),
    (
        "regulatory_compliance_checker",
        "Assess regulatory compliance for a specific industry and identify gaps with remediation steps",
        "legal",
        "batch_v2",
        "You are an expert regulatory compliance consultant. Based on the business description and industry, identify applicable regulations, assess current compliance posture, and provide a remediation roadmap.\n\nInput: {input}\n\nReturn JSON with keys: applicable_regulations, compliance_status (list of {regulation, status, gaps, remediation}), priority_actions, documentation_needed, training_requirements, audit_preparation, timeline, disclaimer.",
        schema("Industry, business activities, jurisdiction, current compliance measures, specific regulatory concerns")
    ),
    (
        "legal_document_summarizer",
        "Summarize complex legal documents into plain language with key terms highlighted",
        "legal",
        "batch_v2",
        "You are an expert legal analyst and plain language specialist. Summarize the provided legal document into clear, accessible language. Highlight key obligations, rights, deadlines, and potential risks.\n\nInput: {input}\n\nReturn JSON with keys: document_type, plain_language_summary, key_obligations, key_rights, important_deadlines, financial_terms, risk_areas, questions_to_ask_lawyer, disclaimer.",
        schema("Legal document text or key excerpts to summarize and explain")
    ),
    (
        "dispute_resolution_advisor",
        "Advise on dispute resolution options including negotiation, mediation, and arbitration",
        "legal",
        "batch_v2",
        "You are an expert dispute resolution specialist. Based on the described dispute, analyze the situation, recommend the most appropriate resolution method, and provide a strategic approach for achieving a favorable outcome.\n\nInput: {input}\n\nReturn JSON with keys: dispute_analysis, resolution_options (list of {method, pros, cons, estimated_cost, timeline}), recommended_approach, negotiation_strategy, evidence_to_gather, settlement_considerations, escalation_path, disclaimer.",
        schema("Nature of the dispute, parties involved, amount at stake, relationship importance, any prior attempts")
    ),

    # =========================================================================
    # SECURITY (14)
    # =========================================================================
    (
        "password_strength_analyzer",
        "Analyze password strength and provide specific improvement recommendations",
        "security",
        "batch_v2",
        "You are an expert cybersecurity specialist. Analyze the described password practices (NOT actual passwords) for strength factors and provide specific, actionable recommendations for improvement following NIST guidelines.\n\nInput: {input}\n\nReturn JSON with keys: strength_assessment, vulnerability_factors, improvement_recommendations, password_manager_advice, mfa_recommendation, common_mistakes_to_avoid, best_practices.",
        schema("Description of password practices (length, complexity, reuse habits) - NEVER send actual passwords")
    ),
    (
        "phishing_email_detector",
        "Analyze an email for phishing indicators and provide a threat assessment",
        "security",
        "batch_v2",
        "You are an expert email security analyst. Analyze the provided email content for phishing indicators, social engineering tactics, and suspicious elements. Provide a clear threat assessment and recommended actions.\n\nInput: {input}\n\nReturn JSON with keys: threat_level (safe/suspicious/likely_phishing/confirmed_phishing), indicators_found (list of {indicator, severity, explanation}), social_engineering_tactics, recommended_actions, reporting_steps, prevention_tips.",
        schema("Email subject, sender, body text, any links (defanged), and any suspicious elements noticed")
    ),
    (
        "security_audit_checklist",
        "Generate a comprehensive security audit checklist for an organization or system",
        "security",
        "batch_v2",
        "You are an expert information security auditor. Create a comprehensive security audit checklist tailored to the organization's infrastructure, covering network, application, data, physical, and personnel security.\n\nInput: {input}\n\nReturn JSON with keys: audit_sections (list of {area, items: list of {check, priority, compliance_standard, pass_criteria}}), audit_timeline, tools_needed, documentation_required, remediation_framework.",
        schema("Organization type, infrastructure (cloud/on-prem/hybrid), industry, compliance requirements, team size")
    ),
    (
        "incident_response_planner",
        "Create a structured incident response plan for security breaches and cyber incidents",
        "security",
        "batch_v2",
        "You are an expert incident response specialist. Create a comprehensive incident response plan covering detection, containment, eradication, recovery, and lessons learned. Include roles, communication templates, and escalation procedures.\n\nInput: {input}\n\nReturn JSON with keys: ir_phases (list of {phase, steps, responsible_roles, timeline}), communication_plan, escalation_matrix, containment_strategies, evidence_preservation, recovery_procedures, post_incident_review, regulatory_notification_requirements.",
        schema("Organization type, infrastructure, team size, critical assets, compliance requirements")
    ),
    (
        "data_breach_notification_writer",
        "Draft data breach notification letters compliant with relevant regulations",
        "security",
        "batch_v2",
        "You are an expert data breach response specialist. Draft a clear, compliant data breach notification that covers all legally required elements, maintains transparency, and provides actionable steps for affected individuals.\n\nInput: {input}\n\nReturn JSON with keys: notification_letter, required_elements_checklist, regulatory_requirements, notification_timeline, remediation_offerings, faq_for_affected, internal_communication, media_statement_draft, legal_review_notes.",
        schema("Breach type, data exposed, number of affected individuals, jurisdiction, discovery date, remediation steps taken")
    ),
    (
        "access_control_policy_writer",
        "Create a comprehensive access control policy with role-based permissions and review procedures",
        "security",
        "batch_v2",
        "You are an expert identity and access management specialist. Create a comprehensive access control policy implementing least privilege, role-based access, and regular review procedures.\n\nInput: {input}\n\nReturn JSON with keys: policy_sections (list of {title, content}), role_definitions, permission_matrix, access_request_workflow, review_schedule, provisioning_procedures, deprovisioning_procedures, audit_requirements, compliance_mapping.",
        schema("Organization size, systems/applications, current access management, compliance requirements")
    ),
    (
        "vulnerability_assessment_guide",
        "Guide through vulnerability assessment methodology including tools, processes, and remediation",
        "security",
        "batch_v2",
        "You are an expert vulnerability management specialist. Provide a comprehensive vulnerability assessment guide including methodology, recommended tools, scanning procedures, risk scoring, and remediation prioritization.\n\nInput: {input}\n\nReturn JSON with keys: assessment_methodology, scope_definition, tools_recommended (list of {tool, purpose, cost}), scanning_procedures, risk_scoring_framework, remediation_priorities, reporting_template, continuous_monitoring_plan.",
        schema("Environment type (web app/network/cloud), technology stack, compliance requirements, team expertise level")
    ),
    (
        "security_awareness_trainer",
        "Design security awareness training content for employees at various levels",
        "security",
        "batch_v2",
        "You are an expert security awareness training specialist. Design engaging security awareness training content that educates employees on current threats, security best practices, and organizational policies.\n\nInput: {input}\n\nReturn JSON with keys: training_modules (list of {title, content_outline, duration, interactive_elements}), phishing_simulation_scenarios, assessment_questions, reinforcement_activities, metrics_to_track, annual_calendar, gamification_elements.",
        schema("Employee roles/departments, current security culture, known risk areas, training budget, delivery preference")
    ),
    (
        "encryption_advisor",
        "Advise on encryption strategies for data at rest and in transit",
        "security",
        "batch_v2",
        "You are an expert cryptography and data protection specialist. Based on the data protection needs, recommend appropriate encryption strategies, algorithms, key management practices, and implementation approaches.\n\nInput: {input}\n\nReturn JSON with keys: encryption_recommendations (list of {data_type, at_rest, in_transit, algorithm, key_length}), key_management_plan, implementation_steps, compliance_alignment, performance_considerations, common_pitfalls, tools_and_libraries.",
        schema("Data types to protect, infrastructure, compliance requirements, performance constraints")
    ),
    (
        "network_security_planner",
        "Design a network security architecture with defense-in-depth strategies",
        "security",
        "batch_v2",
        "You are an expert network security architect. Design a defense-in-depth network security plan covering segmentation, firewall rules, intrusion detection, monitoring, and incident response integration.\n\nInput: {input}\n\nReturn JSON with keys: network_architecture, segmentation_plan, firewall_rules_strategy, ids_ips_recommendations, monitoring_strategy, vpn_configuration, zero_trust_elements, wireless_security, implementation_phases, budget_estimate.",
        schema("Current network topology, business requirements, remote access needs, compliance requirements, budget range")
    ),
    (
        "compliance_gap_analyzer",
        "Identify compliance gaps between current security posture and required frameworks",
        "security",
        "batch_v2",
        "You are an expert compliance assessment specialist. Analyze the gap between the organization's current security posture and the target compliance framework, providing a prioritized remediation roadmap.\n\nInput: {input}\n\nReturn JSON with keys: framework_requirements, current_state_assessment, gaps_identified (list of {requirement, current_status, gap, remediation, priority, effort}), remediation_roadmap, quick_wins, resource_requirements, timeline_estimate.",
        schema("Target framework (SOC2/ISO27001/HIPAA/PCI-DSS), current security measures, organization size, industry")
    ),
    (
        "threat_model_creator",
        "Create a threat model for a system or application identifying threats and mitigations",
        "security",
        "batch_v2",
        "You are an expert threat modeling specialist. Using STRIDE methodology, create a comprehensive threat model for the described system, identifying threat actors, attack vectors, and appropriate mitigations.\n\nInput: {input}\n\nReturn JSON with keys: system_overview, trust_boundaries, threat_actors, stride_analysis (list of {category, threats, likelihood, impact, mitigations}), attack_tree, risk_matrix, mitigation_priorities, residual_risks.",
        schema("System description, architecture, data flows, user types, external integrations, deployment environment")
    ),
    (
        "security_policy_writer",
        "Draft comprehensive information security policies aligned with industry frameworks",
        "security",
        "batch_v2",
        "You are an expert information security policy specialist. Draft a comprehensive security policy covering the requested areas, aligned with industry frameworks and best practices. Include implementation guidance.\n\nInput: {input}\n\nReturn JSON with keys: policy_document (list of {section, content}), scope, roles_and_responsibilities, enforcement, exceptions_process, review_cycle, related_policies, compliance_mapping, implementation_guide.",
        schema("Policy area, organization type, industry, compliance frameworks, specific requirements")
    ),
    (
        "penetration_test_planner",
        "Plan a penetration testing engagement with scope, methodology, and deliverables",
        "security",
        "batch_v2",
        "You are an expert penetration testing consultant. Plan a comprehensive penetration testing engagement including scope definition, methodology, rules of engagement, testing phases, and reporting requirements.\n\nInput: {input}\n\nReturn JSON with keys: engagement_scope, rules_of_engagement, methodology, testing_phases (list of {phase, objectives, techniques, tools, duration}), reporting_requirements, success_criteria, risk_mitigation_during_test, timeline, team_requirements.",
        schema("Target systems, testing type (black box/gray box/white box), objectives, constraints, compliance drivers")
    ),

    # =========================================================================
    # PRODUCTIVITY (14)
    # =========================================================================
    (
        "meeting_agenda_generator",
        "Create structured meeting agendas with time allocations, objectives, and action items",
        "productivity",
        "batch_v2",
        "You are an expert meeting facilitator. Create a structured meeting agenda that maximizes productivity, keeps discussions focused, and ensures clear outcomes and accountability.\n\nInput: {input}\n\nReturn JSON with keys: meeting_title, objective, attendees_needed, agenda_items (list of {topic, owner, duration_minutes, objective, discussion_points}), pre_meeting_prep, decision_points, parking_lot, follow_up_template, total_duration.",
        schema("Meeting purpose, key topics, attendees, available time, any decisions needed")
    ),
    (
        "time_management_advisor",
        "Analyze time usage patterns and recommend personalized productivity strategies",
        "productivity",
        "batch_v2",
        "You are an expert productivity coach. Based on the described work patterns, challenges, and goals, provide personalized time management strategies, tools, and habits that fit the individual's work style.\n\nInput: {input}\n\nReturn JSON with keys: current_pattern_analysis, time_wasters_identified, strategies (list of {strategy, implementation, expected_impact}), daily_routine_suggestion, tools_recommended, habit_building_plan, weekly_review_template.",
        schema("Current work schedule, biggest time wasters, work style, goals, role/responsibilities")
    ),
    (
        "project_timeline_planner",
        "Create detailed project timelines with milestones, dependencies, and resource allocation",
        "productivity",
        "batch_v2",
        "You are an expert project manager. Create a detailed project timeline with clear milestones, task dependencies, resource allocation, and buffer time. Identify critical path and risk points.\n\nInput: {input}\n\nReturn JSON with keys: project_phases (list of {phase, tasks: list of {task, duration, dependencies, assignee}), milestones, critical_path, resource_allocation, risk_buffer, total_duration, gantt_chart_data, review_points.",
        schema("Project description, deliverables, team size/roles, deadline, constraints, dependencies")
    ),
    (
        "decision_matrix_creator",
        "Build a weighted decision matrix to evaluate options objectively",
        "productivity",
        "batch_v2",
        "You are an expert decision analysis consultant. Create a weighted decision matrix that helps evaluate options objectively using relevant criteria, weights, and scoring to reach a data-informed recommendation.\n\nInput: {input}\n\nReturn JSON with keys: criteria (list of {name, weight, rationale}), options_scored (list of {option, scores: list of {criterion, score, reasoning}, weighted_total}), recommendation, sensitivity_analysis, considerations_beyond_matrix.",
        schema("Decision to make, options being considered, important criteria, any constraints or priorities")
    ),
    (
        "brainstorming_facilitator",
        "Facilitate structured brainstorming sessions with diverse ideation techniques",
        "productivity",
        "batch_v2",
        "You are an expert innovation facilitator. Design a structured brainstorming session using proven ideation techniques that generate diverse, creative ideas while maintaining focus on the objective.\n\nInput: {input}\n\nReturn JSON with keys: session_plan, warm_up_activity, ideation_rounds (list of {technique, duration, instructions, expected_output}), evaluation_criteria, idea_clustering_method, next_steps_template, facilitation_tips, remote_adaptation.",
        schema("Topic/challenge, team size, session duration, remote or in-person, any constraints")
    ),
    (
        "goal_setting_framework",
        "Create a comprehensive goal-setting framework with SMART goals and action plans",
        "productivity",
        "batch_v2",
        "You are an expert executive coach and goal-setting specialist. Transform the described aspirations into SMART goals with detailed action plans, milestones, accountability mechanisms, and progress tracking.\n\nInput: {input}\n\nReturn JSON with keys: goals (list of {goal_statement, specific, measurable, achievable, relevant, time_bound, action_steps, milestones, obstacles, accountability}), quarterly_review_schedule, tracking_method, motivation_strategies.",
        schema("Aspirations/objectives, timeframe, current situation, available resources, areas of life/work")
    ),
    (
        "habit_tracker_designer",
        "Design a personalized habit tracking system with triggers, routines, and rewards",
        "productivity",
        "batch_v2",
        "You are an expert behavioral psychologist and habit formation specialist. Design a personalized habit tracking system based on the habit loop (cue, routine, reward) with progressive difficulty and accountability.\n\nInput: {input}\n\nReturn JSON with keys: habits_to_track (list of {habit, cue, routine, reward, frequency, difficulty_progression}), tracking_method, weekly_review_template, streak_milestones, accountability_system, recovery_plan_for_breaks, habit_stacking_suggestions.",
        schema("Habits to build or break, current routine, motivation level, preferred tracking method")
    ),
    (
        "delegation_advisor",
        "Advise on what to delegate, to whom, and how to delegate effectively",
        "productivity",
        "batch_v2",
        "You are an expert leadership and delegation coach. Based on the described workload and team capabilities, identify tasks to delegate, match them to team members, and provide a delegation framework for effective handoff.\n\nInput: {input}\n\nReturn JSON with keys: tasks_to_delegate (list of {task, delegate_to, reason, authority_level, check_in_frequency}), tasks_to_keep, delegation_conversation_template, monitoring_plan, feedback_framework, common_delegation_mistakes.",
        schema("Current task list, team members and their skills/experience, time constraints, development goals")
    ),
    (
        "focus_technique_guide",
        "Recommend and implement deep focus techniques tailored to work style and challenges",
        "productivity",
        "batch_v2",
        "You are an expert cognitive performance coach. Based on the described work environment and focus challenges, recommend specific deep work techniques, environment optimizations, and tools for sustained concentration.\n\nInput: {input}\n\nReturn JSON with keys: focus_assessment, recommended_techniques (list of {technique, description, implementation, best_for}), environment_optimizations, digital_minimalism_tips, energy_management, break_strategies, tools_recommended, daily_focus_schedule.",
        schema("Work type, biggest distractions, work environment, energy patterns, current focus challenges")
    ),
    (
        "workflow_automation_planner",
        "Identify automation opportunities in workflows and design implementation plans",
        "productivity",
        "batch_v2",
        "You are an expert business process automation consultant. Analyze the described workflows, identify automation opportunities, and create an implementation plan with ROI estimates and tool recommendations.\n\nInput: {input}\n\nReturn JSON with keys: workflow_analysis, automation_opportunities (list of {process, current_time, automated_time, tool, implementation_effort, roi}), implementation_roadmap, quick_wins, tool_stack_recommendation, change_management_plan, total_time_savings.",
        schema("Current workflows described step by step, tools currently used, pain points, team technical level")
    ),
    (
        "knowledge_base_organizer",
        "Design a knowledge management system with taxonomy, templates, and maintenance processes",
        "productivity",
        "batch_v2",
        "You are an expert knowledge management specialist. Design a structured knowledge base system with logical taxonomy, standardized templates, contribution workflows, and maintenance processes.\n\nInput: {input}\n\nReturn JSON with keys: taxonomy (hierarchical categories), templates (list of {type, structure}), contribution_workflow, quality_standards, search_optimization, maintenance_schedule, migration_plan, tool_recommendations, governance_model.",
        schema("Knowledge types to organize, team size, current tools, search needs, compliance requirements")
    ),
    (
        "retrospective_facilitator",
        "Design and facilitate team retrospectives with structured formats and action items",
        "productivity",
        "batch_v2",
        "You are an expert agile coach and retrospective facilitator. Design an engaging retrospective format tailored to the team's situation, with structured activities, psychological safety measures, and actionable outcomes.\n\nInput: {input}\n\nReturn JSON with keys: retro_format, icebreaker, activities (list of {name, duration, instructions, materials}), discussion_prompts, action_item_framework, follow_up_plan, remote_facilitation_tips, psychological_safety_measures.",
        schema("Team size, sprint/project just completed, known issues, remote or in-person, previous retro topics")
    ),
    (
        "okr_writer",
        "Write clear OKRs (Objectives and Key Results) with measurable outcomes",
        "productivity",
        "batch_v2",
        "You are an expert OKR coach. Transform the described goals into well-structured OKRs with inspiring objectives and measurable key results. Ensure alignment with higher-level goals and include scoring guidance.\n\nInput: {input}\n\nReturn JSON with keys: okrs (list of {objective, key_results: list of {kr, metric, target, baseline, scoring_guide}}), alignment_notes, stretch_vs_committed, tracking_cadence, common_pitfalls, quarterly_check_in_template.",
        schema("Goals/priorities for the period, team/individual, company-level OKRs to align with, timeframe")
    ),
    (
        "priority_matrix_builder",
        "Build an Eisenhower or impact/effort priority matrix for task management",
        "productivity",
        "batch_v2",
        "You are an expert productivity strategist. Organize the provided tasks into a priority matrix (urgent/important or impact/effort), provide clear categorization rationale, and recommend execution order.\n\nInput: {input}\n\nReturn JSON with keys: matrix_type, quadrants (list of {quadrant, tasks: list of {task, rationale}}), execution_order, delegation_candidates, elimination_candidates, weekly_planning_template, review_frequency.",
        schema("List of tasks/projects, deadlines, impact assessment, available time/resources")
    ),

    # =========================================================================
    # TRAVEL (14)
    # =========================================================================
    (
        "itinerary_planner",
        "Create a detailed day-by-day travel itinerary with logistics, activities, and recommendations",
        "travel",
        "batch_v2",
        "You are an expert travel planner. Create a detailed, day-by-day itinerary balancing must-see attractions, local experiences, logistics, and downtime. Include practical tips and alternatives for weather contingencies.\n\nInput: {input}\n\nReturn JSON with keys: trip_overview, daily_plans (list of {day, date, morning, afternoon, evening, meals, transportation, notes}), packing_essentials, budget_estimate, booking_priorities, contingency_plans, local_tips.",
        schema("Destination, travel dates, interests, budget range, travel style, group composition, must-see items")
    ),
    (
        "packing_list_generator",
        "Generate a customized packing list based on destination, duration, and activities",
        "travel",
        "batch_v2",
        "You are an expert travel organizer. Create a comprehensive, customized packing list considering the destination's climate, planned activities, trip duration, and any special requirements.\n\nInput: {input}\n\nReturn JSON with keys: essentials, clothing (list with quantities), toiletries, electronics, documents, activity_specific_items, carry_on_vs_checked, packing_tips, items_to_buy_there, weight_saving_tips.",
        schema("Destination, travel dates, duration, activities planned, airline baggage limits, special needs")
    ),
    (
        "travel_budget_calculator",
        "Create a detailed travel budget breakdown with saving tips and cost estimates",
        "travel",
        "batch_v2",
        "You are an expert travel budget advisor. Create a detailed budget breakdown for the trip covering all expense categories, with tips for saving money without sacrificing experience quality.\n\nInput: {input}\n\nReturn JSON with keys: budget_breakdown (list of {category, estimated_cost, notes}), total_estimate, saving_tips, splurge_worthy_experiences, hidden_costs_to_watch, payment_tips, daily_spending_guide, budget_tracking_method.",
        schema("Destination, duration, travel style (budget/mid-range/luxury), number of travelers, must-do activities")
    ),
    (
        "visa_requirement_checker",
        "Check visa requirements and provide application guidance for international travel",
        "travel",
        "batch_v2",
        "You are an expert immigration and visa consultant. Based on the traveler's nationality and destination, provide visa requirement information, application guidance, and timeline recommendations.\n\nInput: {input}\n\nReturn JSON with keys: visa_required (boolean), visa_type, requirements, application_process, processing_time, cost, required_documents, tips, common_rejection_reasons, alternatives, disclaimer_to_verify_with_embassy.",
        schema("Passport nationality, destination country, purpose of travel, duration of stay")
    ),
    (
        "hotel_comparison_analyzer",
        "Compare hotel options based on location, amenities, reviews, and value",
        "travel",
        "batch_v2",
        "You are an expert hospitality analyst. Compare the provided hotel options across key criteria including location convenience, amenities, review sentiment, price-value ratio, and suitability for the traveler's needs.\n\nInput: {input}\n\nReturn JSON with keys: comparison_matrix, scores (per hotel), recommendation, pros_cons_each, location_analysis, value_assessment, booking_tips, alternative_accommodation_types.",
        schema("Hotel options with prices, destination, travel purpose, must-have amenities, budget")
    ),
    (
        "flight_search_advisor",
        "Provide flight search strategies and booking advice for the best deals",
        "travel",
        "batch_v2",
        "You are an expert flight booking strategist. Based on the travel requirements, provide flight search strategies, optimal booking timing, routing options, and money-saving tips.\n\nInput: {input}\n\nReturn JSON with keys: search_strategy, optimal_booking_window, routing_options, airline_recommendations, loyalty_program_tips, fare_class_advice, baggage_strategy, airport_tips, price_alert_recommendation, flexible_date_savings.",
        schema("Origin, destination, travel dates (flexible?), class preference, budget, number of passengers")
    ),
    (
        "local_cuisine_guide",
        "Create a local food guide with must-try dishes, restaurant types, and dining etiquette",
        "travel",
        "batch_v2",
        "You are an expert culinary travel guide. Create a comprehensive local cuisine guide covering must-try dishes, where to find authentic food, dining etiquette, food safety tips, and dietary accommodation advice.\n\nInput: {input}\n\nReturn JSON with keys: must_try_dishes (list of {dish, description, where_to_find, price_range}), restaurant_types, street_food_guide, dining_etiquette, food_safety_tips, dietary_accommodations, tipping_customs, food_tour_recommendation.",
        schema("Destination, dietary restrictions, adventurousness level, budget, any food allergies")
    ),
    (
        "travel_safety_advisor",
        "Provide destination-specific safety advice including health, crime, and natural hazard awareness",
        "travel",
        "batch_v2",
        "You are an expert travel safety consultant. Provide comprehensive safety information for the destination covering health risks, crime prevention, natural hazards, and emergency preparedness.\n\nInput: {input}\n\nReturn JSON with keys: overall_safety_rating, health_precautions, crime_awareness (list of {risk, prevention}), natural_hazards, scam_awareness, emergency_contacts, insurance_recommendation, safe_transportation, neighborhoods_to_avoid, women_solo_travel_tips (if applicable).",
        schema("Destination, travel dates, solo or group, traveler profile, specific safety concerns")
    ),
    (
        "cultural_etiquette_guide",
        "Provide a comprehensive cultural etiquette guide for respectful travel",
        "travel",
        "batch_v2",
        "You are an expert cross-cultural communication specialist. Provide a comprehensive cultural etiquette guide that helps travelers show respect, avoid faux pas, and connect meaningfully with local culture.\n\nInput: {input}\n\nReturn JSON with keys: greetings_and_gestures, dress_code, dining_etiquette, religious_site_behavior, tipping_customs, photography_rules, business_etiquette (if applicable), taboo_topics, useful_local_phrases, gift_giving_customs, dos_and_donts.",
        schema("Destination country/region, purpose of visit, specific social situations expected")
    ),
    (
        "travel_insurance_advisor",
        "Advise on travel insurance coverage needs and help compare policy options",
        "travel",
        "batch_v2",
        "You are an expert travel insurance specialist. Based on the trip details and traveler profile, recommend appropriate coverage levels, explain policy types, and help evaluate insurance options.\n\nInput: {input}\n\nReturn JSON with keys: recommended_coverage, coverage_types_explained, policy_comparison_criteria, claim_process_overview, pre_existing_condition_notes, adventure_activity_coverage, trip_cancellation_scenarios, cost_estimate_range, fine_print_to_watch.",
        schema("Destination, trip duration, activities planned, traveler age, pre-existing conditions, trip cost")
    ),
    (
        "road_trip_planner",
        "Plan an epic road trip with routes, stops, timing, and logistics",
        "travel",
        "batch_v2",
        "You are an expert road trip planner. Design an optimized road trip route with scenic stops, must-see attractions, rest points, fuel planning, and accommodation suggestions. Balance driving time with experiences.\n\nInput: {input}\n\nReturn JSON with keys: route_overview, daily_driving_plan (list of {day, start, end, distance, driving_time, stops: list of {name, type, duration}}), fuel_budget, accommodation_suggestions, road_trip_essentials, playlist_themes, emergency_kit, vehicle_prep_checklist.",
        schema("Start/end points, duration, interests, vehicle type, budget, must-see stops, scenic preference")
    ),
    (
        "business_travel_organizer",
        "Organize business travel with efficiency, policy compliance, and productivity in mind",
        "travel",
        "batch_v2",
        "You are an expert corporate travel manager. Organize business travel that maximizes productivity, ensures policy compliance, and maintains traveler wellbeing. Include preparation checklists and expense tracking guidance.\n\nInput: {input}\n\nReturn JSON with keys: travel_plan, pre_trip_checklist, meeting_preparation, expense_categories, productivity_tips, jet_lag_management, networking_opportunities, policy_compliance_notes, post_trip_actions, loyalty_program_strategy.",
        schema("Destination, purpose, meeting schedule, travel policy constraints, duration, preferences")
    ),
    (
        "adventure_travel_planner",
        "Plan adventure travel experiences with safety, equipment, and skill level considerations",
        "travel",
        "batch_v2",
        "You are an expert adventure travel specialist. Plan an adventure trip that matches the traveler's skill level, fitness, and risk tolerance while maximizing the experience. Include safety protocols and equipment lists.\n\nInput: {input}\n\nReturn JSON with keys: adventure_activities (list of {activity, difficulty, duration, requirements, safety_notes}), fitness_preparation, equipment_list, guide_service_recommendations, insurance_requirements, weather_considerations, emergency_protocols, skill_building_progression.",
        schema("Destination, adventure activities desired, fitness level, experience level, group size, budget")
    ),
    (
        "travel_review_writer",
        "Write detailed, helpful travel reviews for accommodations, restaurants, or attractions",
        "travel",
        "batch_v2",
        "You are an expert travel writer and reviewer. Write a detailed, balanced travel review that helps future travelers make informed decisions. Cover key aspects, include specific details, and provide a fair overall assessment.\n\nInput: {input}\n\nReturn JSON with keys: headline, review_body, rating_breakdown (list of {category, score, comment}), highlights, lowlights, tips_for_future_visitors, who_its_best_for, value_assessment, overall_rating.",
        schema("Place reviewed (hotel/restaurant/attraction), experience details, what went well, what didn't, who you'd recommend it to")
    ),
]


def main():
    parser = argparse.ArgumentParser(description="Batch-insert ~161 skills into skills.db")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be inserted without actually inserting")
    parser.add_argument("--db", default=DB_PATH, help="Path to skills.db")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"ERROR: Database not found at {args.db}")
        return

    category_counts = {}
    total = 0

    if args.dry_run:
        print("=== DRY RUN — no changes will be made ===\n")
        for name, desc, cat, src, tmpl, inp_schema in SKILLS:
            category_counts[cat] = category_counts.get(cat, 0) + 1
            total += 1
            print(f"  [{cat}] {name}: {desc[:80]}...")
        print(f"\n--- Summary (dry run) ---")
        for cat, count in sorted(category_counts.items()):
            print(f"  {cat}: {count}")
        print(f"  TOTAL: {total}")
        return

    conn = sqlite3.connect(args.db)
    inserted = 0

    for name, desc, cat, src, tmpl, inp_schema in SKILLS:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO skills (name, description, category, source, prompt_template, model, input_schema) "
                "VALUES (?, ?, ?, ?, ?, 'claude-haiku', ?)",
                (name, desc, cat, src, tmpl, inp_schema)
            )
            if conn.total_changes > inserted + sum(category_counts.values()) - category_counts.get(cat, 0):
                pass  # tracking below
            category_counts[cat] = category_counts.get(cat, 0) + 1
        except sqlite3.Error as e:
            print(f"  ERROR inserting {name}: {e}")

    conn.commit()

    # Count actually inserted by checking which names exist
    cursor = conn.execute(
        "SELECT category, COUNT(*) FROM skills WHERE source='batch_v2' GROUP BY category"
    )
    actual_counts = dict(cursor.fetchall())

    conn.close()

    print("--- Insertion Summary ---")
    for cat, count in sorted(category_counts.items()):
        actual = actual_counts.get(cat, 0)
        print(f"  {cat}: {count} attempted, {actual} in DB with source=batch_v2")
    print(f"  TOTAL attempted: {sum(category_counts.values())}")
    print(f"  TOTAL in DB (batch_v2): {sum(actual_counts.values())}")


if __name__ == "__main__":
    main()
