/*
 * Contextual help catalog for Movie Multiverse.
 *
 * Keys under FIELD_HELP match HTML form `name` attributes. TEXT_HELP keys
 * match visible labels, buttons, links, and table headings. Keeping definitions
 * here makes player/admin wording consistent and gives maintainers one concise
 * place to update a mechanic's explanation.
 */
(() => {
  'use strict';
  const FIELD_HELP = {
    username: 'Account login name. This is separate from the public character name.',
    email: 'Account recovery/contact address. It is not displayed to other players.',
    password: 'Account password. Passwords are never displayed or written to activity logs.',
    character_name: 'Public, permanent character name shown in combat, feeds, and scoreboards.',
    sex: 'Character identity selection. It does not change combat statistics.',
    class_id: 'Permanent class choice. Class bonuses are added to the character’s base statistics.',
    level: 'Progress tier. Level affects HP, eligible opponents, rewards, and content difficulty.',
    str_bonus: 'Strength added by this class or equipped item.',
    end_bonus: 'Endurance added by this class or equipped item.',
    agi_bonus: 'Agility added by this class or equipped item.',
    lck_bonus: 'Luck added by this class or equipped item.',
    per_bonus: 'Perception added by this class or equipped item.',
    xp: 'Experience earned through combat and certain events. Thresholds award a level and stat point.',
    current_hp: 'Current health. At 1 HP a player is defeated but not killed.',
    current_ap: 'Action Points available for activities. AP is awarded at reset and through scheduled trickles.',
    credits: 'Spendable currency used by the Tavern, Blacksmith, Shop, and other systems.',
    str_stat: 'Strength: improves melee damage and inventory capacity.',
    end_stat: 'Endurance: improves maximum HP, AP allowance, and regeneration.',
    agi_stat: 'Agility: improves ranged attack and damage, Armor Class, initiative, stealing, escape, detection, and observation.',
    lck_stat: 'Luck: improves critical results, random events, stealing, escape, detection, observation, and repairs.',
    per_stat: 'Perception: improves observation, detection, and selected economy checks.',
    str_alloc: 'Creation points assigned to Strength before class bonuses.',
    end_alloc: 'Creation points assigned to Endurance before class bonuses.',
    agi_alloc: 'Creation points assigned to Agility before class bonuses.',
    lck_alloc: 'Creation points assigned to Luck before class bonuses.',
    per_alloc: 'Creation points assigned to Perception before class bonuses.',
    preset: 'Fills the NPC behavior fields with a suggested archetype. You may customize the values afterward.',
    player_hunter: 'Motivation to seek legal PvP fights. Higher values make PvP more important than other goals.',
    boss_killer: 'Motivation to challenge bosses for progression, rewards, and completion.',
    hoarder: 'Motivation to acquire and retain unique special items.',
    thief: 'Motivation to alternate legal PvP stealing attempts with boss fights for progression.',
    aggression: 'Willingness to select stronger opponents and keep attacking instead of defending or escaping.',
    self_preservation: 'Willingness to heal, brace, avoid risk, and escape when health becomes dangerous.',
    repair_tendency: 'Likelihood of visiting the Blacksmith when equipped gear loses durability.',
    enabled: 'Paused NPCs remain in the world but do not receive scheduled automated decisions.',
    item_key: 'Content item to grant directly. Unique specials must currently be available in the global pool.',
    constant_name: 'Configuration key used by the game. Change only a setting whose effect you understand.',
    value: 'Stored configuration value. It is converted to the setting’s expected number, boolean, or text type.',
    reason: 'Required audit explanation describing why this administrative or balancing change was made.',
    name: 'Display name used anywhere this content appears in the game.',
    is_active: 'Disabled content remains in historical records but is excluded from new gameplay selection.',
    weapon_type: 'Weapon category used by combat flavor and related rules.',
    damage_die: 'Dice expression rolled for base weapon damage, such as d6 or 2d4.',
    damage_type: 'Damage category checked against armor resistance.',
    credit_cost: 'Base credit value used when purchasing, selling, rewarding, or comparing this item.',
    drop_chance: 'Probability weight used when this content is considered for a drop.',
    starting_durability: 'Durability assigned when a new copy enters an inventory.',
    ac_bonus: 'Armor Class added while equipped, making attacks less likely to hit.',
    res_blade: 'Damage reduction against blade attacks.', res_blunt: 'Damage reduction against blunt attacks.',
    res_ballistic: 'Damage reduction against ballistic attacks.', res_energy: 'Damage reduction against energy attacks.',
    res_arcane: 'Damage reduction against arcane attacks.', res_explosive: 'Damage reduction against explosive attacks.',
    res_venom: 'Damage reduction against venom attacks.',
    associated_to: 'Movie character or content record this unique item belongs to.',
    association_type: 'Whether the associated owner is a Boss, Minion, or Protagonist.',
    initiative_bonus: 'Bonus applied when determining who acts first in combat.',
    extra_attack: 'Chance or flag allowing an additional attack when the special’s rules trigger.',
    crit_chance_bonus: 'Additional critical-hit probability supplied by this special.',
    crit_dmg_multiplier: 'Additional multiplier applied to critical-hit damage.',
    xp_multiplier: 'Fractional bonus to XP rewards; 0.10 means ten percent.',
    credit_multiplier: 'Fractional bonus to credit rewards.',
    steal_bonus: 'Bonus applied to opposed stealing rolls and applicable steal rewards.',
    bonus_ap: 'Additional AP capacity supplied while this special is equipped.',
    hp_regen_bonus: 'Additional health restored by applicable regeneration effects.',
    durability_reduction: 'Fractional reduction to durability loss; 0.10 means ten percent less loss.',
    shop_discount: 'Fractional reduction to shop purchase prices.',
    sell_bonus: 'Fractional increase to eligible sale proceeds.',
    encounter_bonus: 'Bonus applied to the chance or quality of random encounters.',
    bonus_damage_type: 'Damage category used by this itemâ€™s separate bonus-damage component. It receives its own resistance and weakness check.',
    bonus_damage_amount: 'Additional typed damage added to a successful attack. Critical hits also multiply this component.',
    world_boss_hunter: 'Motivation to spend AP attacking the active shared weekly boss.',
    preference: 'Automatic behavior used when another player attacks you while you are not choosing the response.',
    minimum_bid: 'Lowest public bid accepted when this auction opens.',
    duration_hours: 'Auction remains open for 24 or 48 hours, then transfers the item or releases it if no bid was placed.',
    amount: 'Bid amount. Credits are reserved immediately and returned automatically if another player outbids you.',
    perk_id: 'Permanent perk choice for this milestone level. Only currently eligible, unowned perks are shown.',
    start: 'Include log entries on or after this date.', end: 'Include log entries through this date.',
    category: 'Restrict results to one kind of recorded activity.', errors_only: 'Show only failed actions and errors.'
  };
  const TEXT_HELP = {
    'dashboard': 'Summary of current game state and administrative warnings.',
    'import excel': 'Stage a game-content workbook for validated import at the next reset.',
    'players': 'Inspect characters, histories, inventory, statistics, and administrative state.',
    'npcs': 'Create and manage automated characters that follow ordinary player rules.',
    'items': 'Inspect and rebalance weapon, armor, and special-item definitions.',
    'analytics': 'Aggregate gameplay data used to evaluate progression and balance.',
    'health & audit': 'Inspect failed actions, scheduler runs, integrity warnings, and admin changes.',
    'config': 'Edit global gameplay constants. Changes can affect every player.',
    'logs': 'Inspect import errors, orphan recovery, and failed queued actions.',
    'rules reference': 'Creator reference for gameplay flows, formulas, and the settings that control them.',
    'how to play': 'Open the complete player guide for combat, progression, equipment, economy, and logs.',
    'midnight reset': 'Immediately run the normal UTC reset sequence. This affects the entire game.',
    'create npc': 'Create an ordinary player character controlled by the NPC decision scheduler.',
    'run one turn': 'Run one NPC decision immediately without waiting for its scheduled time.',
    'spend ap now': 'Run repeated ordinary NPC decisions until AP or useful progress stops.',
    'retire': 'Permanently remove a character from active play while retaining historical records.',
    'retire character': 'Permanently disable login, end combat, and return unique specials to circulation.',
    'ban player': 'Disciplinary removal that wipes credits and inventory. Retirement is a different operation.',
    'save item': 'Apply visible item changes and record the required reason in the admin audit log.',
    'grant item': 'Place this item in the selected NPC inventory under normal uniqueness constraints.',
    'activity log': 'Open this character’s chronological action and error history.',
    'boss': 'Spend AP to challenge an available movie villain.',
    'pvp': 'Spend AP to challenge a player allowed by the PvP eligibility rules.',
    'tavern': 'Spend AP and credits to restore missing health.',
    'blacksmith': 'Spend resources to restore durability on damaged equipment.',
    'shop': 'Browse available equipment and unique special items.',
    'auction': 'Pay the listed AP once to enter public auctions for unequipped special items.',
    'world boss': 'Attack the weekly enemyâ€™s shared HP pool and compete for damage-ranking rewards.',
    'character': 'Review statistics, effects, inventory, equipment, and combat preference.',
    'equipment': 'Manage your weapon, outfit, and special item, inspect their effects, and preview loadout changes.',
    'active players': 'Show characters that performed a recorded action during the last five minutes.',
    'scoreboards': 'Compare public progression and combat records.',
    'attack': 'Roll d20 plus the relevant STR or AGI modifier against Armor Class, then roll weapon damage on a hit.',
    'brace': 'Restore 15% of missing HP and gain temporary Armor Class until the next attack resolves. Bracing also wears equipped armor.',
    'observe': 'Use an opposed AGI, LCK, and PER roll to permanently learn enemy defenses and abilities.',
    'steal': 'Use an opposed AGI and LCK roll. Success tries an unequipped item first, then credits, then consolation XP.',
    'escape': 'Spend AP and win an opposed AGI and LCK roll to end combat; failure uses the turn.',
    'str': 'Strength improves melee damage and inventory capacity.',
    'end': 'Endurance improves HP, AP allowance, and regeneration.',
    'agi': 'Agility improves ranged attack and damage, Armor Class, initiative, stealing, escape, detection, and observation.',
    'lck': 'Luck influences critical results, events, stealing, escape, detection, observation, and repairs.',
    'per': 'Perception influences observation, detection, and selected economy checks.',
    'lvl': 'Current character level.', 'hp': 'Current health compared with maximum health.',
    'ap': 'Current Action Points compared with the character’s allowance.', 'cr': 'Current spendable credits.',
    'possible damage': 'Normal pre-resistance damage range for the equipped weapon, gear bonuses, and relevant STR or AGI modifier.',
    'armor class': 'Attack total required to hit you: 10 plus half effective AGI and all active outfit, special-item, perk, and temporary AC bonuses.',
    'critical damage': 'Pre-resistance damage range on a critical hit. Enemy resistance and weakness apply afterward.',
    'attack bonus': 'Added to the d20 attack roll: half STR for melee or half AGI for ranged, plus level-based proficiency.',
    'critical range': 'Natural d20 results that can critically hit. The percentage is the chance before accuracy and other combat rules.',
    'initiative modifier': 'Added to initiative from half effective AGI plus active item, perk, status, and encounter bonuses.',
    'steal modifier': 'Added to opposed steal rolls from half AGI, half LCK, and equipped steal bonuses.',
    'escape modifier': 'Added to opposed escape rolls from half AGI plus half LCK.',
    'observe modifier': 'Added to opposed Observe rolls from half AGI, half LCK, and half PER.',
    'brace healing': 'Percentage of currently missing HP restored when you use Brace.',
    'tavern healing': 'Percentage of currently missing HP restored by a successful Tavern visit.',
    'durability protection': 'Percentage reduction to weapon, outfit, and special-item wear, including PvP defeat wear.',
    'encounter bonus': 'Equipment/perk modifier that improves random-event frequency, favorable outcomes, and good-event rarity. It does not alter minion interruptions.',
    'extra attack': 'Makes one additional attack whenever you choose Attack. Accuracy, criticals, damage, and resistance are rolled separately.',
    'xp reward bonus': 'Percentage added to victory, steal, defeat, drop, and world-boss attempt XP rewards.',
    'credit reward bonus': 'Percentage added to generated combat and world-boss credit rewards; it does not create extra credits taken from another player.',
    'daily ap': 'AP allowance from base AP, effective END, and AP bonuses, subject to the configured cap.',
    'hp regen/ap': 'Health restored when an AP-spending action applies passive regeneration.',
    'inventory limit': 'Maximum carried items before encumbrance penalties, based on the configured base plus effective STR.',
    'shop discount': 'Purchase-price reduction from half effective PER plus active shop-discount effects, limited by the global cap.',
    'sell bonus': 'Additional percentage added to the configured equipment resale rate.',
    'place public bid': 'Reserve this many credits on the listing. A later bidder returns your reserved credits automatically.',
    'begin auction': 'Place the selected unequipped special on public hold for the chosen duration.',
    'attack world boss': 'Spend the listed AP to begin one normal-length attempt against the shared weekly HP pool.',
    'combat preference': 'Controls your automatic response when another player attacks while you are not actively choosing actions.',
    'damage types': 'Damage categories supplied by the equipped weapon and every active typed bonus-damage effect.',
    'resistances': 'Outfit, special-item, and perk protections. One source halves matching damage; stacked sources use the configured resistance floor.',
    'preview': 'Compare this item’s hypothetical loadout values without equipping it or changing game state.'
  };
  const normalize = value => (value || '').replace(/\s+/g, ' ').trim().toLowerCase().replace(/\s*\([^)]*\)\s*$/, '');
  function attach(element, text, showBadge) {
    if (!text || element.dataset.helpAttached) return;
    element.dataset.helpAttached = '1'; element.title = text; element.setAttribute('aria-description', text);
    if (!showBadge) return;
    const badge = document.createElement('span'); badge.className = 'context-help'; badge.tabIndex = 0;
    badge.setAttribute('role', 'note'); badge.setAttribute('aria-label', text); badge.dataset.help = text; badge.textContent = '?';
    // Table headings must retain exactly one DOM cell per data column. Adding
    // the badge as a sibling of <th> creates an anonymous extra table cell and
    // shifts every heading away from its values. Keep badges inside headings
    // (and label-like elements); ordinary controls may still use a sibling.
    if (element.matches('th,.label,label')) element.appendChild(badge);
    else element.insertAdjacentElement('afterend', badge);
  }
  function install() {
    document.querySelectorAll('input[name],select[name],textarea[name]').forEach(control => {
      const text = FIELD_HELP[control.name]; if (!text) return;
      attach(control, text, false);
      const label = control.closest('label') || (control.id && document.querySelector(`label[for="${control.id}"]`));
      if (label) attach(label, text, true);
    });
    document.querySelectorAll('button,a,th,.label,[data-help-key]').forEach(element => {
      const key = element.dataset.helpKey || normalize(element.textContent);
      const text = TEXT_HELP[key]; if (text) attach(element, text, element.matches('th,.label'));
    });
  }
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', install) : install();
})();
