---
# The numbers the code uses. Everything below the line is read by Claude.
protein_min_g_per_100kcal: 10
skip_min_purchase_coupons: true
---

# My diet

I lift, eat lean, and cook for myself. These rules decide which items on the Carnival ad are
worth a trip. None of this is about restriction for its own sake; it's about not spending a
grocery run on food that doesn't serve training.

The value is in the cutting. A Carnival ad is dominated by beer, soda, snacks, and fatty deli
meat, and a good week keeps maybe a third of it. Don't pad the list to make it look fuller: a
short list I can trust is the point.

## Classify before judging

Applying the wrong test is the main way this goes wrong, so first decide what each item is,
by the role it plays in a kitchen:

1. **Protein**: meat, poultry, fish, shellfish, eggs, and dairy bought mainly for its protein
   (milk, yogurt, cottage cheese, fresh and aged cheeses). Deli and cured meats count here
   too: bacon, ham, salami, bologna, hot dogs, chorizo. They get the protein rule.
2. **Produce, legumes, and spices**: vegetables, fruit, beans, herbs, chiles, aromatics.
3. **Carbs, fiber, and flavor**: rice, oats, flour, masa, tortillas, bread, pasta, canned
   tomatoes, sauces, salsas, oils, and anything else bought as a base or a seasoning.
4. **Hard cut**: alcohol, beverages, sweets, and ultra-processed food (below). Out regardless
   of anything else. So is anything that isn't food: paper goods, charcoal, plates, soap.

Groups 2 and 3 are judged as what they are. **Never run the protein rule on them.** Beans,
oats, and rice will never clear a protein bar and were never meant to: they're in the cart for
fiber, carbs, and cost per calorie.

## The protein rule (group 1 only)

**A protein item stays only if it delivers at least 10 g of protein per 100 kcal.**

This weeds out things sold as protein that are really fat or sugar wearing a meat label.
Bacon, salami, bologna, and hot dogs are the archetypes: they read as protein in the aisle and
behave as fat in the diet.

You don't compute this. Match each protein item to the row of `nutrition.csv` that describes
it as I'd actually cook it, and the code applies the rule using that row's USDA numbers.

- **Edible portion.** Judge the food as I'd prepare it: bone discarded, poultry skin removed,
  visible fat trimmed. Bone-in chicken thighs are judged as thigh meat. That latitude is for
  fat you can cut away, not a loophole: bacon is bacon however it's cooked, and ground meat
  can't be trimmed after the fact, so it's judged at its stated lean/fat ratio. Pick the row
  for the cut as sold (bone-in or boneless), because the row's yield accounts for the bone.
- **Collagen-dominant cuts fail.** Tripe, stomach, neckbones, trotters, hocks, and skin carry
  protein figures that overstate what the body can use, since most of it is collagen, poor in
  leucine and near-useless for building muscle. Their rows are flagged and fail even when the
  raw ratio squeaks past 10.
- **Calibration.** Skinless chicken breast lands near 19 g per 100 kcal; lean trimmed beef and
  pork cuts 14 to 18; white fish around 20; plain nonfat Greek yogurt near 17; cottage cheese
  just past the bar around 11. Whole eggs come out near 8.8 and fail, because most of their
  calories are fat. Full-fat fresh cheeses like queso fresco and panela fail too, as do cured
  and emulsified meats at 4 to 7. Those are the rule doing its job, not edge cases to rescue.

## Produce, pantry: judge on their own terms

Keep anything a self-cooking lifter would genuinely use: vegetables, fruit, dried and canned
legumes, chiles, tomatillos, nopales, aromatics, rice, oats, masa and corn flour, corn
tortillas, plain flour, canned tomatoes, plain frozen vegetables and fruit, cooking oil. Nopales
and cactus pears are real vegetables and fruit; unfamiliar is not a reason to cut.

Cut only for a substantive reason: it's a novelty, it's a sugary or heavily processed version
of a whole food, or nobody cooking for themselves would find a use for it.

## Hard cuts, no exceptions

- **Alcohol.** Beer, wine, spirits, hard seltzer, canned cocktails.
- **Beverages.** Anything bought to drink: soda, energy and sports drinks, juice and juice
  drinks, drinkable yogurt, coffee and cocoa drinks, bottled and sparkling water, coconut water,
  plant milks, coffee creamer. Drinking calories doesn't serve this diet.
- **Sweets.** Ice cream, cookies, candy, pastries, cake mix and frosting, pudding and gelatin
  cups, syrup, sweetened yogurt, and anything else whose reason to exist is sugar.
- **Ultra-processed food.** Industrial formulations built from refined ingredients and
  additives you wouldn't find in a home kitchen (NOVA group 4): chips, instant noodles, boxed
  rice and pasta side-dish mixes, frozen waffles and taquitos and pot pies, instant flavored
  oatmeal packets, bottled dressings, margarine, processed cheese spreads, sweetened peanut
  butter, condensed soups, packaged snack cakes.

### What ultra-processed does not mean

This is the category most often over-applied, and over-cutting here strips out the cheap
staples that make the ad worth reading. Canning, freezing, drying, and milling are not
ultra-processing. Keep:

- canned beans, canned vegetables, canned whole or diced tomatoes, plain tomato sauce
- plain frozen vegetables and fruit
- rice, dried beans, plain oats, flour, masa
- corn tortillas, and tortillas generally
- plain Greek yogurt, cottage cheese, canned fish in water

The test is not "did a factory touch it" but "is this a whole food preserved, or a formulation
assembled from refined ingredients". A can of black beans is beans. A can of condensed soup is
a formulation.

**Sweetened or flavored versions of fine staples are cut**: flavored yogurt, sweetened peanut
butter, flavored instant oatmeal, seasoned rice mixes. Say that the plain version would have
passed.

## Items with alternatives

Many cells offer a choice: "Gala Apples or Peruano Beans", "Pork Shank or Marinated or Plain
Drumsticks". Judge each alternative on its own; only the ones that pass are shown. "Selected
varieties" means some varieties on the shelf may be fine and others not: judge what the ad
most likely means, and say so when it matters.

## $30-minimum coupons

The ad's coupon band offers prices that only apply with a $30 purchase I don't plan to make,
so those items are skipped (the `skip_min_purchase_coupons` setting above). An item excluded
there may also appear elsewhere on the page at a normal sale price; that listing stays in.
