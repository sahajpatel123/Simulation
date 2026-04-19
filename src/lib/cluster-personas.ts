/**
 * Pure frontend mapping: cluster_id → persona (first name, tagline, copy, reach).
 * Keys match `app/simulation/clusters/registry.py` (52 clusters).
 */

export interface ClusterPersona {
  clusterId: string
  firstName: string
  tagline: string
  description: string
  reachEstimate: string
  gender: 'she' | 'he' | 'they'
  emoji: string
}

export const CLUSTER_PERSONAS: Record<string, ClusterPersona> = {
  // ── HIGH ECONOMIC POWER ──
  metro_power_professional: {
    clusterId: 'metro_power_professional',
    firstName: 'Arjun',
    tagline: 'Pays Annual, Demands Proof',
    description:
      'Senior Bangalore professional who converts on performance evidence and pays annually without hesitation — if you earn it.',
    reachEstimate: '~4,800 people like him',
    gender: 'he',
    emoji: '💼',
  },
  senior_enterprise_decision_maker: {
    clusterId: 'senior_enterprise_decision_maker',
    firstName: 'Vikram',
    tagline: 'Needs Committee Sign-Off',
    description:
      'C-suite buyer who cannot say yes alone — security reviews, vendor evaluation, and three signature levels stand between you and his budget.',
    reachEstimate: '~2,400 people like him',
    gender: 'he',
    emoji: '🏛️',
  },
  high_income_early_adopter: {
    clusterId: 'high_income_early_adopter',
    firstName: 'Priya',
    tagline: 'Buys on Novelty, Evangelises if Delighted',
    description:
      'Affluent tech enthusiast who will pre-order on instinct and tell 30 friends — or publicly return it if disappointed.',
    reachEstimate: '~3,200 people like her',
    gender: 'she',
    emoji: '⚡',
  },
  affluent_metro_late_majority: {
    clusterId: 'affluent_metro_late_majority',
    firstName: 'Meena',
    tagline: 'Converts After Peer Vouches',
    description:
      'High-income professional who has seen too many products overpromise. She needs 10+ reviews and one trusted peer before she moves.',
    reachEstimate: '~3,200 people like her',
    gender: 'she',
    emoji: '🔍',
  },
  high_income_hardware_enthusiast: {
    clusterId: 'high_income_hardware_enthusiast',
    firstName: 'Rahul',
    tagline: 'Deep Spec Comparison, YouTube First',
    description:
      'Well-off buyer who watches 5 YouTube reviews before touching your checkout page. Specs must justify the premium.',
    reachEstimate: '~2,400 people like him',
    gender: 'he',
    emoji: '📊',
  },
  wealthy_health_conscious_buyer: {
    clusterId: 'wealthy_health_conscious_buyer',
    firstName: 'Deepa',
    tagline: 'Clinical Credibility or Nothing',
    description:
      'High-income buyer who will pay premium for health products but only if the science is real and the packaging matches the price.',
    reachEstimate: '~2,400 people like her',
    gender: 'she',
    emoji: '🌿',
  },

  // ── MIDDLE INCOME URBAN ──
  urban_mid_income_saas_buyer: {
    clusterId: 'urban_mid_income_saas_buyer',
    firstName: 'Kavya',
    tagline: '14-Day Trial, ROI or Churn',
    description:
      'Mid-income professional who starts free trials thoughtfully. She converts if the value is visceral within two weeks — not promised, proven.',
    reachEstimate: '~4,000 people like her',
    gender: 'she',
    emoji: '⏱️',
  },
  urban_mid_income_hardware_considerer: {
    clusterId: 'urban_mid_income_hardware_considerer',
    firstName: 'Sanjay',
    tagline: 'Aggregator Sites, EMI Availability Decides',
    description:
      'Mid-income urban buyer who compares 3-5 options on Amazon and Flipkart. EMI availability is often the final deciding factor.',
    reachEstimate: '~3,200 people like him',
    gender: 'he',
    emoji: '🔄',
  },
  young_urban_professional_first_job: {
    clusterId: 'young_urban_professional_first_job',
    firstName: 'Ananya',
    tagline: 'Converts on Freemium, Upgrades on Visceral Value',
    description:
      '22-27 year old in her first job. High aspiration, constrained budget. Entry price matters enormously — upgrade only if value is felt, not told.',
    reachEstimate: '~4,000 people like her',
    gender: 'she',
    emoji: '🚀',
  },
  urban_couple_joint_purchaser: {
    clusterId: 'urban_couple_joint_purchaser',
    firstName: 'Rohan & Sneha',
    tagline: 'One Researches, Both Decide',
    description:
      'Dual-income couple where one partner researches but both sign off. Gift-wrapping and packaging quality matter for the final yes.',
    reachEstimate: '~2,400 couples like them',
    gender: 'they',
    emoji: '👫',
  },
  mid_income_startup_founder: {
    clusterId: 'mid_income_startup_founder',
    firstName: 'Karan',
    tagline: 'Fast ROI or Fast Churn',
    description:
      'Bootstrapped founder with high digital literacy and shrinking runway. Adopts tools in hours if ROI is fast — churns the moment growth stalls.',
    reachEstimate: '~1,600 people like him',
    gender: 'he',
    emoji: '🛠️',
  },
  urban_working_mother: {
    clusterId: 'urban_working_mother',
    firstName: 'Nandita',
    tagline: 'Safety + Time-Saving + Trusted Peer',
    description:
      'Time-scarce professional mother. She converts on safety, time-saving claims, and one trusted recommendation — not features.',
    reachEstimate: '~2,400 people like her',
    gender: 'she',
    emoji: '⚖️',
  },

  // ── STUDENT / YOUNG ADULT ──
  high_literacy_student_freemium_ceiling: {
    clusterId: 'high_literacy_student_freemium_ceiling',
    firstName: 'Shreya',
    tagline: 'Exhausts Free Tier, Seeks Workarounds',
    description:
      'Tech-savvy student who uses freemium heavily, finds workarounds creatively, and converts only under deadline pressure or genuine necessity.',
    reachEstimate: '~3,200 people like her',
    gender: 'she',
    emoji: '🎓',
  },
  low_literacy_student_passive: {
    clusterId: 'low_literacy_student_passive',
    firstName: 'Raju',
    tagline: 'Discovers via Reels, Drops at Complex Signup',
    description:
      'Student with limited digital skill who discovers products through social content. Any complexity at signup and he is gone — permanently.',
    reachEstimate: '~2,400 people like him',
    gender: 'he',
    emoji: '📱',
  },
  student_high_intent_specific_need: {
    clusterId: 'student_high_intent_specific_need',
    firstName: 'Aishwarya',
    tagline: 'Converts Fast, Churns After Need Met',
    description:
      'Student with an urgent, named need — exam prep, job hunt, visa application. Converts immediately when product directly addresses it. Churns after.',
    reachEstimate: '~2,400 people like her',
    gender: 'she',
    emoji: '🎯',
  },
  college_group_purchase: {
    clusterId: 'college_group_purchase',
    firstName: 'The Group',
    tagline: 'One Pays, Six Share, Cancel if Anyone Leaves',
    description:
      'Friend group subscription where one person pays and 3-6 share. The subscription collapses the moment group dynamics shift.',
    reachEstimate: '~1,600 groups like them',
    gender: 'they',
    emoji: '👥',
  },
  recent_graduate_job_seeker: {
    clusterId: 'recent_graduate_job_seeker',
    firstName: 'Mithun',
    tagline: 'Free Trial + Outcome Story, Churns After Offer',
    description:
      'Fresh graduate investing in career tools. Converts on free trial and a believable outcome story. Churns the day the job offer lands.',
    reachEstimate: '~1,600 people like him',
    gender: 'he',
    emoji: '📄',
  },

  // ── TIER 2 / TIER 3 ──
  tier2_aspirational_founder: {
    clusterId: 'tier2_aspirational_founder',
    firstName: 'Suresh',
    tagline: 'Converts on Perceived ROI, Churns at Day 7',
    description:
      "First-generation entrepreneur from a non-metro city. High motivation, limited runway. If value isn't felt in 7 days, he's gone and won't return.",
    reachEstimate: '~2,400 people like him',
    gender: 'he',
    emoji: '💡',
  },
  tier2_established_business_owner: {
    clusterId: 'tier2_established_business_owner',
    firstName: 'Ramesh',
    tagline: 'Buys Only After Colleague Vouches',
    description:
      "Profitable SME owner in a tier-2 city. Distrusts online-first products completely. A colleague's recommendation is worth more than any ad.",
    reachEstimate: '~2,400 people like him',
    gender: 'he',
    emoji: '🏪',
  },
  tier3_first_time_app_user: {
    clusterId: 'tier3_first_time_app_user',
    firstName: 'Lakshmi',
    tagline: 'Someone Nearby Must Explain It',
    description:
      'Rural consumer using a smartphone app for the first time. Converts if a trusted person nearby explains it. Drops immediately on any confusion.',
    reachEstimate: '~3,200 people like her',
    gender: 'she',
    emoji: '🌾',
  },
  tier2_price_sensitive_pragmatist: {
    clusterId: 'tier2_price_sensitive_pragmatist',
    firstName: 'Ganesh',
    tagline: 'Cheapest Credible Option Wins',
    description:
      'Middle-class tier-2 buyer who compares aggressively on price. Converts if you are the cheapest credible option — even a 5% difference matters.',
    reachEstimate: '~3,200 people like him',
    gender: 'he',
    emoji: '💰',
  },
  tier3_community_influenced_buyer: {
    clusterId: 'tier3_community_influenced_buyer',
    firstName: 'Parvati',
    tagline: 'Only Buys What the Local Trusted Person Uses',
    description:
      "Rural buyer whose purchase decision is entirely determined by local community norms. If the trusted local hasn't bought it, she won't either.",
    reachEstimate: '~2,400 people like her',
    gender: 'she',
    emoji: '🏘️',
  },
  tier2_educated_young_parent: {
    clusterId: 'tier2_educated_young_parent',
    firstName: 'Divya',
    tagline: 'Safety + Outcome Evidence + Referral',
    description:
      "College-educated parent in a tier-2 city investing in children's future. Converts on safety proof and outcome evidence. Highly receptive to referrals.",
    reachEstimate: '~2,400 people like her',
    gender: 'she',
    emoji: '👶',
  },

  // ── B2B / ENTERPRISE ──
  smb_owner_self_serve: {
    clusterId: 'smb_owner_self_serve',
    firstName: 'Amit',
    tagline: "Saves 2 Hours a Week or It's Gone",
    description:
      'Small business owner who discovers and adopts tools independently. Tests for 14 days. Converts only if the product demonstrably saves 2+ hours per week.',
    reachEstimate: '~2,400 people like him',
    gender: 'he',
    emoji: '⏰',
  },
  smb_owner_referral_dependent: {
    clusterId: 'smb_owner_referral_dependent',
    firstName: 'Prakash',
    tagline: "Will Not Buy From a Brand He Hasn't Heard Of",
    description:
      'SMB owner who only adopts tools vouched for by someone in his network. Cold acquisition is nearly impossible. Referral is the only door.',
    reachEstimate: '~2,400 people like him',
    gender: 'he',
    emoji: '🤝',
  },
  mid_market_it_decision_maker: {
    clusterId: 'mid_market_it_decision_maker',
    firstName: 'Neha',
    tagline: '30-Day PoC, API Docs, Then CFO',
    description:
      'IT head of a 200-person company. Runs a 30-day proof of concept, requires SSO and API documentation, then presents to the CFO. Three gatekeepers.',
    reachEstimate: '~1,600 people like her',
    gender: 'she',
    emoji: '🔐',
  },
  enterprise_procurement_gatekeeper: {
    clusterId: 'enterprise_procurement_gatekeeper',
    firstName: 'Sunil',
    tagline: 'Blocks Any Vendor Not on the Approved List',
    description:
      "Procurement manager whose primary job is compliance. If you are not on the approved vendor list, this conversation never begins.",
    reachEstimate: '~800 people like him',
    gender: 'he',
    emoji: '🚧',
  },
  technical_founder_evaluator: {
    clusterId: 'technical_founder_evaluator',
    firstName: 'Arjun',
    tagline: 'Reads Source Code Before Pricing Page',
    description:
      'CTO or technical co-founder who evaluates products by reading docs and API quality. Converts on technical credibility — never on marketing.',
    reachEstimate: '~1,600 people like him',
    gender: 'he',
    emoji: '💻',
  },
  non_technical_co_founder_buyer: {
    clusterId: 'non_technical_co_founder_buyer',
    firstName: 'Pooja',
    tagline: 'Case Studies + G2 Score = Decision',
    description:
      'Business co-founder making tool decisions without engineering input. Relies entirely on case studies, testimonials, and third-party review scores.',
    reachEstimate: '~1,600 people like her',
    gender: 'she',
    emoji: '📋',
  },

  // ── HARDWARE SPECIFIC ──
  early_hardware_adopter_tech_enthusiast: {
    clusterId: 'early_hardware_adopter_tech_enthusiast',
    firstName: 'Dev',
    tagline: 'Pre-Orders on Kickstarter, Shares Unboxing',
    description:
      'Hobbyist who buys new hardware categories purely for novelty. Shares the unboxing publicly — delighted or disappointed, both go online.',
    reachEstimate: '~1,600 people like him',
    gender: 'he',
    emoji: '📦',
  },
  considered_hardware_researcher: {
    clusterId: 'considered_hardware_researcher',
    firstName: 'Rajesh',
    tagline: '10 Reviews, 5 Videos, Most Authoritative Source Wins',
    description:
      'Methodical buyer who spends 3-8 weeks comparing hardware. The most credible, authoritative source he finds becomes his purchase channel.',
    reachEstimate: '~2,400 people like him',
    gender: 'he',
    emoji: '🔬',
  },
  value_hardware_buyer: {
    clusterId: 'value_hardware_buyer',
    firstName: 'Mohan',
    tagline: 'Best Under ₹X, Sensitive to 5% Difference',
    description:
      "Price-to-performance buyer who converts on 'best under ₹X' positioning. A 5% price difference genuinely changes his decision.",
    reachEstimate: '~2,400 people like him',
    gender: 'he',
    emoji: '🏷️',
  },
  gift_hardware_buyer: {
    clusterId: 'gift_hardware_buyer',
    firstName: 'Sunita',
    tagline: 'Buys Brand She Recognises, Packaging Decides',
    description:
      'Buying as a gift with low personal knowledge. Recognisable brand + beautiful packaging = purchase. Unknown brand = immediate exit.',
    reachEstimate: '~1,600 people like her',
    gender: 'she',
    emoji: '🎁',
  },
  replacement_hardware_buyer: {
    clusterId: 'replacement_hardware_buyer',
    firstName: 'Vijay',
    tagline: 'Re-Buys Same Brand Unless Previous Was Bad',
    description:
      'Urgency-driven buyer replacing a broken device. Deeply brand-loyal — re-buys the same brand automatically unless the last experience was poor.',
    reachEstimate: '~1,600 people like him',
    gender: 'he',
    emoji: '🔁',
  },
  health_hardware_skeptic: {
    clusterId: 'health_hardware_skeptic',
    firstName: "Dr. Sharma's Patient",
    tagline: 'Clinical Study or Doctor Endorsement Required',
    description:
      'Interested in health outcomes but deeply unconvinced by wearable claims. A clinical study or direct doctor endorsement is the minimum entry point.',
    reachEstimate: '~1,600 people like them',
    gender: 'they',
    emoji: '🩺',
  },
  health_hardware_enthusiast: {
    clusterId: 'health_hardware_enthusiast',
    firstName: 'Fitness Priya',
    tagline: 'Upgrades Every 18 Months on Accuracy',
    description:
      'Obsessive health tracker who upgrades frequently and converts on data accuracy and sensor specs. Already bought your competitor — convince her to switch.',
    reachEstimate: '~1,600 people like her',
    gender: 'she',
    emoji: '🏃',
  },
  smart_home_early_adopter: {
    clusterId: 'smart_home_early_adopter',
    firstName: 'Techie Rohit',
    tagline: 'Ecosystem Compatibility First, Everything Else Second',
    description:
      "Enthusiast building a connected home. If your device doesn't play nicely with his existing ecosystem, the conversation ends before it starts.",
    reachEstimate: '~1,600 people like him',
    gender: 'he',
    emoji: '🏠',
  },

  // ── SPECIAL BEHAVIORAL ──
  anxiety_driven_researcher: {
    clusterId: 'anxiety_driven_researcher',
    firstName: 'Meera',
    tagline: '20 Tabs, 3 Abandoned Carts, Eventually Buys',
    description:
      'Over-researches every purchase out of fear of regret. Opens 20+ tabs, reads every review, abandons cart multiple times — but often does convert, eventually.',
    reachEstimate: '~2,400 people like her',
    gender: 'she',
    emoji: '😰',
  },
  impulsive_trend_follower: {
    clusterId: 'impulsive_trend_follower',
    firstName: 'Viral Raj',
    tagline: 'Sees Reel, Buys, Forgets in 2 Weeks',
    description:
      'Converts instantly on trending social content. High volume, low LTV. Churns just as fast as he converts — unless the product builds a habit quickly.',
    reachEstimate: '~3,200 people like him',
    gender: 'he',
    emoji: '🌊',
  },
  loyalist_returning_buyer: {
    clusterId: 'loyalist_returning_buyer',
    firstName: 'Priya L.',
    tagline: 'Renews Automatically, Churns Only on Price Spike',
    description:
      'Previous customer who renews without thinking. The only things that move her are significant price increases or noticeable product degradation.',
    reachEstimate: '~2,400 people like her',
    gender: 'she',
    emoji: '♻️',
  },
  price_anchor_manipulated_buyer: {
    clusterId: 'price_anchor_manipulated_buyer',
    firstName: 'Deal Hunter Deepak',
    tagline: 'Crossed-Out Price = Trigger, False Anchor = Return',
    description:
      "Responds powerfully to anchoring effects. 'Originally ₹2,999, now ₹999' converts him instantly — but if the anchor was false, he returns and posts about it.",
    reachEstimate: '~2,400 people like him',
    gender: 'he',
    emoji: '✂️',
  },
  peer_pressure_converter: {
    clusterId: 'peer_pressure_converter',
    firstName: 'Follow-the-Group Farhan',
    tagline: 'Buys After 3rd Peer Mention',
    description:
      'Converts because peers visibly use the product. Word-of-mouth is his only reliable acquisition channel — the first two peer mentions plant the seed.',
    reachEstimate: '~2,400 people like him',
    gender: 'he',
    emoji: '👥',
  },
  deliberate_minimalist: {
    clusterId: 'deliberate_minimalist',
    firstName: 'Minimal Maya',
    tagline: 'Replaces 2 Tools and Saves Money, or No',
    description:
      'Intentionally avoids excess subscriptions. The only pitch that works: your product replaces two things she already pays for and costs less combined.',
    reachEstimate: '~1,600 people like her',
    gender: 'she',
    emoji: '🧘',
  },
  productivity_maximiser: {
    clusterId: 'productivity_maximiser',
    firstName: '3-Hours-a-Week Tarun',
    tagline: 'Converts on ROI Headline, Becomes Power User if True',
    description:
      "Converts on a credible time-saving headline. If '3 hours/week saved' is real, he becomes your most active power user and your best evangelist.",
    reachEstimate: '~2,400 people like him',
    gender: 'he',
    emoji: '⚡',
  },
  budget_constrained_high_intent: {
    clusterId: 'budget_constrained_high_intent',
    firstName: 'Waiting-for-Sale Waqar',
    tagline: 'Wishlists, Waits, Converts on Any Discount',
    description:
      'Genuinely wants the product but cannot afford full price. Has it wishlisted. Any discount triggers conversion — and he has the highest LTV if retained.',
    reachEstimate: '~3,200 people like him',
    gender: 'he',
    emoji: '⏳',
  },
  passive_enterprise_user: {
    clusterId: 'passive_enterprise_user',
    firstName: 'Mandated Manas',
    tagline: 'Uses Because Required, Advocates Only if Excellent',
    description:
      'Individual contributor using a tool his company mandated. Has no personal agency in the purchase. Becomes an advocate only if the product is genuinely excellent.',
    reachEstimate: '~1,600 people like him',
    gender: 'he',
    emoji: '🔒',
  },
  burnt_previously_buyer: {
    clusterId: 'burnt_previously_buyer',
    firstName: 'Sarah — Burned Before, High Guard',
    tagline: 'Free Trial + Money-Back + Similar Testimonials',
    description:
      'Had a bad experience with a similar product and is deeply skeptical of the category. Free trial, money-back guarantee, and testimonials from similar users are the minimum.',
    reachEstimate: '~1,600 people like her',
    gender: 'she',
    emoji: '🛡️',
  },
  retiree_digital_explorer: {
    clusterId: 'retiree_digital_explorer',
    firstName: 'Dadi Ji',
    tagline: 'Family Member Helps, Large Text, Simple Nav',
    description:
      '65+ retiree cautiously exploring smartphone apps. Converts if a family member helps with setup. Large text, simple navigation, and zero jargon are non-negotiable.',
    reachEstimate: '~1,600 people like them',
    gender: 'they',
    emoji: '👴',
  },
  gig_economy_worker: {
    clusterId: 'gig_economy_worker',
    firstName: 'Platform Pankaj',
    tagline: 'Income Multiplier ROI, Churns for Cheaper',
    description:
      'Freelancer optimising every rupee. Converts only on income-multiplying ROI. Churns the moment a cheaper substitute appears — loyalty is earned daily.',
    reachEstimate: '~1,600 people like him',
    gender: 'he',
    emoji: '🛵',
  },
  vernacular_content_creator: {
    clusterId: 'vernacular_content_creator',
    firstName: 'Bhojpuri Bharat',
    tagline: 'Creator Monetisation Features + Evangelises to Followers',
    description:
      'Regional-language content creator monetising a loyal audience. Converts on monetisation features. If satisfied, evangelises to thousands of followers organically.',
    reachEstimate: '~1,600 people like him',
    gender: 'he',
    emoji: '🎙️',
  },

  // ── NGO / DIASPORA ──
  ngo_nonprofit_buyer: {
    clusterId: 'ngo_nonprofit_buyer',
    firstName: 'Programme Preethi',
    tagline: 'Nonprofit Discount + Committee + Slow Cycle',
    description:
      'NGO programme officer procuring on a restricted budget. Requires nonprofit pricing, goes through committee, and has the longest decision cycle of any segment.',
    reachEstimate: '~800 people like her',
    gender: 'she',
    emoji: '🌍',
  },
  diaspora_remittance_buyer: {
    clusterId: 'diaspora_remittance_buyer',
    firstName: 'NRI Nikhil',
    tagline: 'India-Specific Trust Signals + Gift Delivery',
    description:
      'Indian diaspora member buying for family back home. Converts on India-specific trust signals and reliable gift delivery options. Distance creates anxiety.',
    reachEstimate: '~800 people like him',
    gender: 'he',
    emoji: '✈️',
  },
}

export function getPersona(clusterId: string): ClusterPersona | null {
  return CLUSTER_PERSONAS[clusterId] ?? null
}

export function getPersonaName(clusterId: string): string {
  return CLUSTER_PERSONAS[clusterId]?.firstName ?? clusterId
}

export function getPersonaTagline(clusterId: string): string {
  return CLUSTER_PERSONAS[clusterId]?.tagline ?? ''
}

export function getAllPersonas(): ClusterPersona[] {
  return Object.values(CLUSTER_PERSONAS)
}
