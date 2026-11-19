-- Seed data for GustoBot recipe tables.
-- Populates sample cuisines, tools, ingredients, recipes, steps, and relations.

USE recipe_db;
SET NAMES utf8mb4;

START TRANSACTION;

-- Base cuisines
INSERT INTO cuisines (name, cooking_style, typical_tools)
VALUES
    ('川菜', '辣味浓郁，讲究麻辣鲜香与复合口感。', JSON_ARRAY('炒锅', '砂锅')),
    ('粤菜', '清淡鲜美，强调食材本味与火候掌控。', JSON_ARRAY('蒸锅', '炒锅')),
    ('家常菜', '注重方便快捷，口味温和适合日常家庭。', JSON_ARRAY('炒锅', '汤锅')),
    ('湘菜', '香辣酸辣，重油重色，擅用腌制与熏制工艺。', JSON_ARRAY('炒锅', '砂锅'));

-- Cooking tools
INSERT INTO cooking_tools (name, type, material, capacity)
VALUES
    ('炒锅', 'pan', '碳钢', '32cm'),
    ('蒸锅', 'pot', '不锈钢', '28cm'),
    ('汤锅', 'pot', '不锈钢', '5L'),
    ('平底锅', 'pan', '不粘涂层', '28cm'),
    ('电饭煲', 'other', '复合材质', '3L'),
    ('砧板', 'other', '竹', '40cm'),
    ('菜刀', 'knife', '不锈钢', '8寸'),
    ('锅铲', 'other', '不锈钢', '1把'),
    ('腌制碗', 'other', '陶瓷', '2L'),
    ('搅拌碗', 'other', '不锈钢', '2.5L');

-- Ingredient catalog
INSERT INTO ingredients (name, category, calories, protein, carbs, fat, storage_method, shelf_life)
VALUES
    ('鸡胸肉', '肉类-原料', 165.00, 31.00, 0.00, 3.60, '冷藏', 3),
    ('花生米', '坚果-辅料', 567.00, 25.80, 16.10, 49.20, '常温干燥', 30),
    ('青椒', '蔬菜-辅料', 20.00, 0.90, 4.60, 0.20, '冷藏', 5),
    ('干辣椒', '调味-调料', 318.00, 12.00, 56.00, 17.00, '常温干燥', 180),
    ('花椒', '调味-调料', 285.00, 10.00, 30.00, 16.00, '常温干燥', 365),
    ('姜', '香辛-调料', 80.00, 1.80, 17.80, 0.80, '冷藏', 7),
    ('蒜', '香辛-调料', 149.00, 6.40, 33.10, 0.50, '常温通风', 14),
    ('小葱', '蔬菜-辅料', 32.00, 1.80, 7.30, 0.40, '冷藏', 4),
    ('酱油', '调味-调料', 60.00, 8.00, 6.00, 0.10, '常温避光', 365),
    ('白砂糖', '调味-调料', 387.00, 0.00, 100.00, 0.00, '常温干燥', 365),
    ('米醋', '调味-调料', 18.00, 0.10, 0.90, 0.00, '常温避光', 365),
    ('玉米淀粉', '调味-调料', 381.00, 0.00, 91.00, 0.10, '常温干燥', 365),
    ('食用油', '调味-调料', 884.00, 0.00, 0.00, 100.00, '常温避光', 365),
    ('鲈鱼', '水产-原料', 97.00, 18.00, 0.00, 2.60, '冷藏', 2),
    ('料酒', '调味-调料', 52.00, 0.40, 4.60, 0.10, '常温避光', 365),
    ('蒸鱼豉油', '调味-调料', 72.00, 6.00, 10.00, 0.00, '常温避光', 365),
    ('西兰花', '蔬菜-原料', 34.00, 3.70, 6.60, 0.40, '冷藏', 5),
    ('蒜蓉酱', '调味-调料', 120.00, 4.00, 20.00, 2.00, '冷藏', 30),
    ('牛腩', '肉类-原料', 240.00, 18.00, 0.00, 18.00, '冷藏', 2),
    ('番茄', '蔬菜-原料', 18.00, 0.90, 3.90, 0.20, '常温阴凉', 4),
    ('土豆', '蔬菜-辅料', 77.00, 2.00, 17.00, 0.10, '常温通风', 14),
    ('胡萝卜', '蔬菜-辅料', 41.00, 0.90, 10.00, 0.20, '冷藏', 10),
    ('洋葱', '蔬菜-辅料', 40.00, 1.10, 9.30, 0.10, '常温阴凉', 14),
    ('食盐', '调味-调料', 0.00, 0.00, 0.00, 0.00, '常温干燥', 365),
    ('猪肉里脊', '肉类-原料', 143.00, 21.30, 0.00, 5.40, '冷藏', 2),
    ('蚝油', '调味-调料', 72.00, 5.00, 12.00, 1.00, '常温避光', 365),
    ('猪排骨', '肉类-原料', 240.00, 17.00, 0.00, 19.00, '冷藏', 2),
    ('木耳', '菌类-辅料', 25.00, 1.60, 6.20, 0.20, '常温干燥', 180),
    ('郫县豆瓣酱', '调味-调料', 185.00, 6.00, 20.00, 8.00, '常温避光', 365),
    ('嫩豆腐', '豆制品-原料', 70.00, 8.00, 2.00, 3.00, '冷藏', 3),
    ('鸡蛋', '蛋类-原料', 143.00, 12.60, 1.30, 10.60, '冷藏', 10),
    ('虾仁', '水产-原料', 95.00, 21.00, 0.00, 1.00, '冷藏', 2),
    ('黑胡椒碎', '调味-调料', 255.00, 10.00, 64.00, 3.00, '常温干燥', 365),
    ('香菇', '菌类-辅料', 34.00, 2.20, 6.70, 0.30, '冷藏', 5),
    ('小白菜', '蔬菜-原料', 13.00, 1.50, 2.20, 0.20, '冷藏', 3),
    ('粉丝', '粮食-辅料', 332.00, 0.60, 82.00, 0.20, '常温干燥', 180),
    ('香油', '调味-调料', 884.00, 0.00, 0.00, 100.00, '常温避光', 365),
    ('豆豉', '调味-调料', 200.00, 6.00, 30.00, 6.00, '常温避光', 365),
    ('三文鱼', '水产-原料', 208.00, 20.00, 0.00, 13.00, '冷藏', 2),
    ('鸡腿肉', '肉类-原料', 177.00, 17.00, 0.00, 12.00, '冷藏', 2),
    ('牛里脊', '肉类-原料', 191.00, 21.00, 0.00, 12.00, '冷藏', 2),
    ('西葫芦', '蔬菜-原料', 17.00, 1.20, 3.10, 0.30, '冷藏', 4),
    ('玉米粒', '谷物-辅料', 86.00, 3.20, 19.00, 1.20, '冷藏', 4),
    ('青豆', '豆类-辅料', 118.00, 8.00, 21.00, 1.60, '冷藏', 4),
    ('柠檬', '水果-辅料', 29.00, 1.10, 9.30, 0.30, '冷藏', 7),
    ('杏鲍菇', '菌类-辅料', 35.00, 2.30, 5.80, 0.70, '冷藏', 5);

COMMIT;

-- Cached identifiers for relational inserts
SELECT id INTO @cuisine_sichuan FROM cuisines WHERE name = '川菜';
SELECT id INTO @cuisine_cantonese FROM cuisines WHERE name = '粤菜';
SELECT id INTO @cuisine_home FROM cuisines WHERE name = '家常菜';

SELECT id INTO @tool_wok FROM cooking_tools WHERE name = '炒锅';
SELECT id INTO @tool_steamer FROM cooking_tools WHERE name = '蒸锅';
SELECT id INTO @tool_soup_pot FROM cooking_tools WHERE name = '汤锅';
SELECT id INTO @tool_flat_pan FROM cooking_tools WHERE name = '平底锅';
SELECT id INTO @tool_rice_cooker FROM cooking_tools WHERE name = '电饭煲';
SELECT id INTO @tool_board FROM cooking_tools WHERE name = '砧板';
SELECT id INTO @tool_knife FROM cooking_tools WHERE name = '菜刀';
SELECT id INTO @tool_spatula FROM cooking_tools WHERE name = '锅铲';
SELECT id INTO @tool_marinade_bowl FROM cooking_tools WHERE name = '腌制碗';
SELECT id INTO @tool_mix_bowl FROM cooking_tools WHERE name = '搅拌碗';

SELECT id INTO @ing_chicken FROM ingredients WHERE name = '鸡胸肉';
SELECT id INTO @ing_peanut FROM ingredients WHERE name = '花生米';
SELECT id INTO @ing_green_pepper FROM ingredients WHERE name = '青椒';
SELECT id INTO @ing_dried_chili FROM ingredients WHERE name = '干辣椒';
SELECT id INTO @ing_sichuan_pepper FROM ingredients WHERE name = '花椒';
SELECT id INTO @ing_ginger FROM ingredients WHERE name = '姜';
SELECT id INTO @ing_garlic FROM ingredients WHERE name = '蒜';
SELECT id INTO @ing_scallion FROM ingredients WHERE name = '小葱';
SELECT id INTO @ing_soy_sauce FROM ingredients WHERE name = '酱油';
SELECT id INTO @ing_sugar FROM ingredients WHERE name = '白砂糖';
SELECT id INTO @ing_vinegar FROM ingredients WHERE name = '米醋';
SELECT id INTO @ing_cornstarch FROM ingredients WHERE name = '玉米淀粉';
SELECT id INTO @ing_cooking_oil FROM ingredients WHERE name = '食用油';
SELECT id INTO @ing_sea_bass FROM ingredients WHERE name = '鲈鱼';
SELECT id INTO @ing_shaoxing_wine FROM ingredients WHERE name = '料酒';
SELECT id INTO @ing_steaming_sauce FROM ingredients WHERE name = '蒸鱼豉油';
SELECT id INTO @ing_broccoli FROM ingredients WHERE name = '西兰花';
SELECT id INTO @ing_garlic_paste FROM ingredients WHERE name = '蒜蓉酱';
SELECT id INTO @ing_brisket FROM ingredients WHERE name = '牛腩';
SELECT id INTO @ing_tomato FROM ingredients WHERE name = '番茄';
SELECT id INTO @ing_potato FROM ingredients WHERE name = '土豆';
SELECT id INTO @ing_carrot FROM ingredients WHERE name = '胡萝卜';
SELECT id INTO @ing_onion FROM ingredients WHERE name = '洋葱';
SELECT id INTO @ing_salt FROM ingredients WHERE name = '食盐';
SELECT id INTO @ing_pork_loin FROM ingredients WHERE name = '猪肉里脊';
SELECT id INTO @ing_oyster_sauce FROM ingredients WHERE name = '蚝油';
SELECT id INTO @ing_pork_ribs FROM ingredients WHERE name = '猪排骨';
SELECT id INTO @ing_wood_ear FROM ingredients WHERE name = '木耳';
SELECT id INTO @ing_douban FROM ingredients WHERE name = '郫县豆瓣酱';
SELECT id INTO @ing_soft_tofu FROM ingredients WHERE name = '嫩豆腐';
SELECT id INTO @ing_egg FROM ingredients WHERE name = '鸡蛋';
SELECT id INTO @ing_shrimp FROM ingredients WHERE name = '虾仁';
SELECT id INTO @ing_black_pepper FROM ingredients WHERE name = '黑胡椒碎';
SELECT id INTO @ing_shiitake FROM ingredients WHERE name = '香菇';
SELECT id INTO @ing_bok_choy FROM ingredients WHERE name = '小白菜';
SELECT id INTO @ing_vermicelli FROM ingredients WHERE name = '粉丝';
SELECT id INTO @ing_sesame_oil FROM ingredients WHERE name = '香油';
SELECT id INTO @ing_fermented_black_bean FROM ingredients WHERE name = '豆豉';
SELECT id INTO @ing_salmon FROM ingredients WHERE name = '三文鱼';
SELECT id INTO @ing_chicken_leg FROM ingredients WHERE name = '鸡腿肉';
SELECT id INTO @ing_beef_tenderloin FROM ingredients WHERE name = '牛里脊';
SELECT id INTO @ing_zucchini FROM ingredients WHERE name = '西葫芦';
SELECT id INTO @ing_corn_kernel FROM ingredients WHERE name = '玉米粒';
SELECT id INTO @ing_green_pea FROM ingredients WHERE name = '青豆';
SELECT id INTO @ing_lemon FROM ingredients WHERE name = '柠檬';
SELECT id INTO @ing_king_oyster FROM ingredients WHERE name = '杏鲍菇';

START TRANSACTION;

-- Recipe 1: 宫保鸡丁
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '宫保鸡丁',
    '经典川味热菜，鸡丁鲜嫩、花生酥脆，口感麻辣酸甜平衡。',
    'https://images.example.com/gongbao_jiding.jpg',
    'https://videos.example.com/gongbao_jiding.mp4',
    35, 2, 'medium', @cuisine_sichuan,
    520.00, 48.00, 26.00, 28.00
);
SET @recipe_gongbao := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_gongbao, 1, '切配',
    '鸡胸肉切成均匀小丁，加入酱油、料酒、玉米淀粉拌匀腌制10分钟；青椒切丁，蒜姜切末。',
    10, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '鸡丁大小尽量一致，便于受热均匀。'
);
SET @step_gongbao_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_gongbao_1, @tool_board, '切丁'),
    (@step_gongbao_1, @tool_knife, '切丁'),
    (@step_gongbao_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_gongbao, 2, '炸香',
    '锅内放少量油，中小火将花生米炸至微金黄后捞出沥油备用。',
    3, '中小火', JSON_ARRAY('炒锅', '锅铲'),
    '花生米要不停翻动，避免炒糊。'
);
SET @step_gongbao_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_gongbao_2, @tool_wok, '炸制'),
    (@step_gongbao_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_gongbao, 3, '爆炒',
    '锅中留底油，大火爆香干辣椒与花椒，倒入鸡丁翻炒至变色，再加入蒜姜末、调味汁和青椒丁快速翻匀，最后加入花生米起锅。',
    7, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '调味汁提前兑好，倒入后快速翻炒保持脆感。'
);
SET @step_gongbao_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_gongbao_3, @tool_wok, '爆炒'),
    (@step_gongbao_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_gongbao, @ing_chicken, '300', 'g', '切丁腌制', 10, 1, '鸡腿肉', 480.00, 'main'),
    (@recipe_gongbao, @ing_peanut, '60', 'g', '炸香', 3, 0, NULL, 340.00, 'auxiliary'),
    (@recipe_gongbao, @ing_green_pepper, '80', 'g', '切丁', 2, 0, '黄瓜丁', 18.00, 'auxiliary'),
    (@recipe_gongbao, @ing_dried_chili, '8', 'g', '剪段', 1, 0, NULL, 12.00, 'seasoning'),
    (@recipe_gongbao, @ing_sichuan_pepper, '3', 'g', '备用', 0, 0, NULL, 9.00, 'seasoning'),
    (@recipe_gongbao, @ing_ginger, '10', 'g', '切末', 2, 0, NULL, 8.00, 'seasoning'),
    (@recipe_gongbao, @ing_garlic, '15', 'g', '切末', 2, 0, NULL, 22.00, 'seasoning'),
    (@recipe_gongbao, @ing_soy_sauce, '2', '汤匙', '调汁', 1, 0, NULL, 15.00, 'seasoning'),
    (@recipe_gongbao, @ing_vinegar, '1', '汤匙', '调汁', 1, 0, NULL, 5.00, 'seasoning'),
    (@recipe_gongbao, @ing_sugar, '12', 'g', '调汁', 1, 0, NULL, 46.00, 'seasoning'),
    (@recipe_gongbao, @ing_shaoxing_wine, '1', '汤匙', '腌制', 1, 0, NULL, 8.00, 'seasoning'),
    (@recipe_gongbao, @ing_cornstarch, '10', 'g', '腌制', 1, 0, NULL, 38.00, 'seasoning'),
    (@recipe_gongbao, @ing_cooking_oil, '20', 'g', '烹饪', 0, 0, NULL, 176.80, 'seasoning');

-- Recipe 2: 清蒸鲈鱼
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '清蒸鲈鱼',
    '粤式清蒸做法，鱼肉鲜嫩少油，保留海鲜原汁原味。',
    'https://images.example.com/qingzheng_luyu.jpg',
    'https://videos.example.com/qingzheng_luyu.mp4',
    30, 2, 'easy', @cuisine_cantonese,
    360.00, 52.00, 6.00, 12.00
);
SET @recipe_steamed_bass := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_steamed_bass, 1, '处理',
    '鲈鱼去鳞去腮，剖腹去内脏，鱼身两侧斜刀划花；姜切片，小葱切段备用。',
    8, '常温', JSON_ARRAY('砧板', '菜刀'),
    '刀花不要太深，约到达鱼骨即可。'
);
SET @step_bass_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_bass_1, @tool_board, '清理'),
    (@step_bass_1, @tool_knife, '改刀');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_steamed_bass, 2, '腌制',
    '在鱼身抹上料酒与少许食盐，夹入姜片和葱段，腌制10分钟。',
    10, '常温', JSON_ARRAY('腌制碗'),
    '腌制时给鱼身适度按摩，吸味更均匀。'
);
SET @step_bass_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_bass_2, @tool_marinade_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_steamed_bass, 3, '蒸制',
    '蒸锅入水烧开，将鱼置于蒸盘上，大火蒸8分钟后焖2分钟，取出倒掉蒸汁，撒上葱丝热油激香并淋上蒸鱼豉油。',
    12, '大火', JSON_ARRAY('蒸锅', '锅铲'),
    '蒸制时间视鱼大小调整，保持鱼眼凸起即可。'
);
SET @step_bass_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_bass_3, @tool_steamer, '蒸制'),
    (@step_bass_3, @tool_spatula, '淋油');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_steamed_bass, @ing_sea_bass, '1', '条', '清理划刀', 8, 1, NULL, 290.00, 'main'),
    (@recipe_steamed_bass, @ing_ginger, '20', 'g', '切片', 2, 0, NULL, 16.00, 'auxiliary'),
    (@recipe_steamed_bass, @ing_scallion, '15', 'g', '切段', 2, 0, NULL, 5.00, 'auxiliary'),
    (@recipe_steamed_bass, @ing_shaoxing_wine, '15', 'ml', '腌制', 1, 0, NULL, 8.00, 'seasoning'),
    (@recipe_steamed_bass, @ing_salt, '3', 'g', '抹匀', 1, 0, NULL, 0.00, 'seasoning'),
    (@recipe_steamed_bass, @ing_cooking_oil, '12', 'g', '热油激香', 0, 0, NULL, 106.08, 'seasoning'),
    (@recipe_steamed_bass, @ing_steaming_sauce, '20', 'ml', '淋汁', 0, 0, NULL, 14.40, 'seasoning');

-- Recipe 3: 番茄牛腩煲
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '番茄牛腩煲',
    '长时间慢炖的番茄牛腩，汤汁浓郁，蔬菜软糯。',
    'https://images.example.com/fanqie_niunan.jpg',
    'https://videos.example.com/fanqie_niunan.mp4',
    120, 4, 'medium', @cuisine_home,
    1020.00, 92.00, 48.00, 62.00
);
SET @recipe_brisket := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_brisket, 1, '焯水',
    '牛腩冷水下锅，加入姜片和料酒，大火煮沸撇去浮沫后捞出冲洗干净。',
    10, '大火', JSON_ARRAY('汤锅'),
    '焯水后用温水冲净浮沫，汤更清亮。'
);
SET @step_brisket_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_brisket_1, @tool_soup_pot, '焯水');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_brisket, 2, '炖煮',
    '汤锅重新加热少量油炒香洋葱、蒜末，倒入牛腩、番茄块翻炒，加入清水没过食材，放入胡萝卜、料酒，小火慢炖90分钟。',
    95, '小火', JSON_ARRAY('汤锅'),
    '保持微沸状态，以免肉质变柴。'
);
SET @step_brisket_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_brisket_2, @tool_soup_pot, '炖煮');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_brisket, 3, '收汁',
    '加入土豆块和番茄酱汁，调入酱油、白砂糖、食盐，中火收汁15分钟至汤汁浓稠。',
    15, '中火', JSON_ARRAY('汤锅'),
    '收汁至汤汁挂勺即可，避免炒干。'
);
SET @step_brisket_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_brisket_3, @tool_soup_pot, '收汁');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_brisket, @ing_brisket, '600', 'g', '切块焯水', 12, 1, NULL, 960.00, 'main'),
    (@recipe_brisket, @ing_tomato, '400', 'g', '切块', 5, 0, NULL, 72.00, 'auxiliary'),
    (@recipe_brisket, @ing_onion, '120', 'g', '切丝', 3, 0, NULL, 48.00, 'auxiliary'),
    (@recipe_brisket, @ing_carrot, '150', 'g', '切滚刀', 3, 0, NULL, 61.50, 'auxiliary'),
    (@recipe_brisket, @ing_potato, '180', 'g', '切块', 3, 0, NULL, 138.60, 'auxiliary'),
    (@recipe_brisket, @ing_ginger, '10', 'g', '切片', 2, 0, NULL, 8.00, 'seasoning'),
    (@recipe_brisket, @ing_garlic, '12', 'g', '切末', 2, 0, NULL, 17.88, 'seasoning'),
    (@recipe_brisket, @ing_shaoxing_wine, '20', 'ml', '焯水', 1, 0, NULL, 10.40, 'seasoning'),
    (@recipe_brisket, @ing_soy_sauce, '20', 'ml', '调味', 1, 0, NULL, 12.00, 'seasoning'),
    (@recipe_brisket, @ing_sugar, '8', 'g', '调味', 0, 0, NULL, 30.96, 'seasoning'),
    (@recipe_brisket, @ing_salt, '4', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_brisket, @ing_cooking_oil, '18', 'g', '煸香', 0, 0, NULL, 159.12, 'seasoning');

-- Recipe 4: 蒜蓉西兰花
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '蒜蓉西兰花',
    '爽脆西兰花配蒜蓉酱汁，清香提味，健康低脂。',
    'https://images.example.com/suanrong_xilanhua.jpg',
    'https://videos.example.com/suanrong_xilanhua.mp4',
    20, 3, 'easy', @cuisine_home,
    210.00, 18.00, 26.00, 9.00
);
SET @recipe_broccoli := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_broccoli, 1, '焯烫',
    '西兰花掰成小朵洗净，沸水中加入少许食盐和食用油，焯烫2分钟后迅速过冷水沥干。',
    5, '大火', JSON_ARRAY('汤锅'),
    '焯烫时间不宜过长，保持翠绿色与脆度。'
);
SET @step_broccoli_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_broccoli_1, @tool_soup_pot, '焯烫');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_broccoli, 2, '调酱',
    '蒜蓉酱与蚝油、少量清水混合，调成稠度适中的酱汁备用。',
    3, '常温', JSON_ARRAY('搅拌碗'),
    '可加入几滴香油提升香气。'
);
SET @step_broccoli_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_broccoli_2, @tool_mix_bowl, '调酱');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_broccoli, 3, '快炒',
    '热锅倒入少量油爆香蒜末，倒入酱汁和西兰花翻炒均匀，撒少量食盐调味后即可出锅。',
    5, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '保持大火快炒，避免西兰花出水。'
);
SET @step_broccoli_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_broccoli_3, @tool_wok, '翻炒'),
    (@step_broccoli_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_broccoli, @ing_broccoli, '400', 'g', '掰小朵焯烫', 5, 1, NULL, 136.00, 'main'),
    (@recipe_broccoli, @ing_garlic, '15', 'g', '切末', 2, 0, NULL, 22.35, 'seasoning'),
    (@recipe_broccoli, @ing_garlic_paste, '30', 'g', '调酱', 1, 0, NULL, 36.00, 'seasoning'),
    (@recipe_broccoli, @ing_oyster_sauce, '15', 'g', '调酱', 1, 0, NULL, 10.80, 'seasoning'),
    (@recipe_broccoli, @ing_cooking_oil, '12', 'g', '快炒', 0, 0, NULL, 106.08, 'seasoning'),
    (@recipe_broccoli, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 5: 青椒肉丝
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '青椒肉丝',
    '家常川味快手菜，肉丝滑嫩、青椒脆爽下饭。',
    'https://images.example.com/qingjiao_rous.jpg',
    'https://videos.example.com/qingjiao_rous.mp4',
    25, 2, 'easy', @cuisine_sichuan,
    480.00, 36.00, 22.00, 26.00
);
SET @recipe_pork_pepper := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pork_pepper, 1, '切配',
    '猪里脊切细丝加入酱油、料酒、玉米淀粉抓匀腌10分钟；青椒去籽切丝，洋葱切丝，蒜姜切末。',
    8, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '肉丝逆纹切更易保持嫩度。'
);
SET @step_pork_pepper_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pork_pepper_1, @tool_board, '切丝'),
    (@step_pork_pepper_1, @tool_knife, '切丝'),
    (@step_pork_pepper_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pork_pepper, 2, '滑炒',
    '锅中倒油烧至五成热，下肉丝快速滑散炒至变色后盛出。',
    5, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '油温不可过高，滑炒时间控制在1分钟内。'
);
SET @step_pork_pepper_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pork_pepper_2, @tool_wok, '滑炒'),
    (@step_pork_pepper_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pork_pepper, 3, '合炒',
    '锅中留底油爆香蒜姜，加入青椒丝和洋葱丝炒至断生，再倒回肉丝，加入酱油、白砂糖、米醋调味快速翻匀出锅。',
    3, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '保持大火迅速翻炒，避免青椒出水。'
);
SET @step_pork_pepper_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pork_pepper_3, @tool_wok, '翻炒'),
    (@step_pork_pepper_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_pork_pepper, @ing_pork_loin, '280', 'g', '切丝腌制', 10, 1, '鸡胸肉丝', 400.40, 'main'),
    (@recipe_pork_pepper, @ing_green_pepper, '160', 'g', '切丝', 3, 0, NULL, 32.00, 'auxiliary'),
    (@recipe_pork_pepper, @ing_onion, '80', 'g', '切丝', 2, 0, NULL, 32.00, 'auxiliary'),
    (@recipe_pork_pepper, @ing_garlic, '10', 'g', '切末', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_pork_pepper, @ing_ginger, '8', 'g', '切末', 1, 0, NULL, 6.40, 'seasoning'),
    (@recipe_pork_pepper, @ing_soy_sauce, '18', 'ml', '调味', 1, 0, NULL, 10.80, 'seasoning'),
    (@recipe_pork_pepper, @ing_sugar, '6', 'g', '调味', 0, 0, NULL, 23.22, 'seasoning'),
    (@recipe_pork_pepper, @ing_vinegar, '5', 'ml', '调味', 0, 0, NULL, 1.80, 'seasoning'),
    (@recipe_pork_pepper, @ing_cornstarch, '12', 'g', '腌制', 1, 0, NULL, 45.72, 'seasoning'),
    (@recipe_pork_pepper, @ing_cooking_oil, '18', 'g', '滑炒', 0, 0, NULL, 159.12, 'seasoning'),
    (@recipe_pork_pepper, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 6: 红烧排骨
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '红烧排骨',
    '家常风味红烧排骨，肉质软糯、酱香浓郁，适合配饭。',
    'https://images.example.com/hongshao_paigu.jpg',
    'https://videos.example.com/hongshao_paigu.mp4',
    60, 3, 'medium', @cuisine_home,
    820.00, 58.00, 24.00, 48.00
);
SET @recipe_braised_ribs := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_braised_ribs, 1, '焯水',
    '排骨冷水下锅，加入姜片和料酒，大火煮沸撇去浮沫后捞出备用。',
    8, '大火', JSON_ARRAY('汤锅'),
    '焯水后用温水冲去血沫，保持汤汁清亮。'
);
SET @step_ribs_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_ribs_1, @tool_soup_pot, '焯水');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_braised_ribs, 2, '煸炒',
    '炒锅中倒入适量油，加入姜片、蒜片爆香，放入排骨煸炒至表面微焦。',
    6, '中大火', JSON_ARRAY('炒锅', '锅铲'),
    '煸炒至排骨微焦可提升焦香味。'
);
SET @step_ribs_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_ribs_2, @tool_wok, '煸炒'),
    (@step_ribs_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_braised_ribs, 3, '红烧',
    '加入酱油、白砂糖、料酒翻匀后倒入热水没过排骨，小火焖煮35分钟，最后大火收汁。',
    35, '小火', JSON_ARRAY('汤锅', '锅铲'),
    '收汁时不断翻动，防止糊底。'
);
SET @step_ribs_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_ribs_3, @tool_soup_pot, '焖煮'),
    (@step_ribs_3, @tool_spatula, '收汁');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_braised_ribs, @ing_pork_ribs, '600', 'g', '切段焯水', 10, 1, NULL, 960.00, 'main'),
    (@recipe_braised_ribs, @ing_ginger, '15', 'g', '切片', 2, 0, NULL, 12.00, 'seasoning'),
    (@recipe_braised_ribs, @ing_garlic, '12', 'g', '拍碎', 1, 0, NULL, 17.88, 'seasoning'),
    (@recipe_braised_ribs, @ing_soy_sauce, '25', 'ml', '调味', 1, 0, NULL, 18.00, 'seasoning'),
    (@recipe_braised_ribs, @ing_sugar, '15', 'g', '调味', 0, 0, NULL, 57.90, 'seasoning'),
    (@recipe_braised_ribs, @ing_shaoxing_wine, '20', 'ml', '焯水', 1, 0, NULL, 10.40, 'seasoning'),
    (@recipe_braised_ribs, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_braised_ribs, @ing_cooking_oil, '20', 'g', '煸炒', 0, 0, NULL, 176.80, 'seasoning');

-- Recipe 7: 鱼香肉丝
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '鱼香肉丝',
    '经典川味鱼香肉丝，酸甜辣平衡，开胃下饭。',
    'https://images.example.com/yuxiang_rousi.jpg',
    'https://videos.example.com/yuxiang_rousi.mp4',
    30, 2, 'medium', @cuisine_sichuan,
    620.00, 40.00, 32.00, 32.00
);
SET @recipe_yuxiang := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_yuxiang, 1, '切配',
    '猪里脊切丝，加酱油、淀粉腌制；胡萝卜、青椒切丝，木耳泡发切丝，蒜姜切末。',
    8, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '木耳提前泡发，切丝长度与肉丝相仿。'
);
SET @step_yuxiang_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_yuxiang_1, @tool_board, '切丝'),
    (@step_yuxiang_1, @tool_knife, '切丝'),
    (@step_yuxiang_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_yuxiang, 2, '兑汁',
    '取小碗加入郫县豆瓣酱、酱油、白砂糖、米醋调成鱼香汁备用。',
    2, '常温', JSON_ARRAY('搅拌碗'),
    '调味汁提前兑好，下锅操作更迅速。'
);
SET @step_yuxiang_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_yuxiang_2, @tool_mix_bowl, '调汁');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_yuxiang, 3, '快炒',
    '热锅多油滑散肉丝至变色盛出，锅内留底油依次下蒜姜末、豆瓣酱炒香，倒入配菜与肉丝，淋入调味汁快速翻炒。',
    5, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '保持大火快炒，防止出水影响口感。'
);
SET @step_yuxiang_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_yuxiang_3, @tool_wok, '翻炒'),
    (@step_yuxiang_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_yuxiang, @ing_pork_loin, '320', 'g', '切丝腌制', 8, 1, NULL, 457.60, 'main'),
    (@recipe_yuxiang, @ing_carrot, '60', 'g', '切丝', 2, 0, NULL, 24.60, 'auxiliary'),
    (@recipe_yuxiang, @ing_green_pepper, '80', 'g', '切丝', 2, 0, NULL, 16.00, 'auxiliary'),
    (@recipe_yuxiang, @ing_wood_ear, '30', 'g', '泡发切丝', 10, 0, NULL, 7.50, 'auxiliary'),
    (@recipe_yuxiang, @ing_douban, '20', 'g', '调汁', 1, 0, NULL, 37.00, 'seasoning'),
    (@recipe_yuxiang, @ing_garlic, '15', 'g', '切末', 2, 0, NULL, 22.35, 'seasoning'),
    (@recipe_yuxiang, @ing_ginger, '10', 'g', '切末', 2, 0, NULL, 8.00, 'seasoning'),
    (@recipe_yuxiang, @ing_sugar, '12', 'g', '调汁', 0, 0, NULL, 46.44, 'seasoning'),
    (@recipe_yuxiang, @ing_vinegar, '15', 'ml', '调汁', 0, 0, NULL, 2.70, 'seasoning'),
    (@recipe_yuxiang, @ing_soy_sauce, '15', 'ml', '调汁', 0, 0, NULL, 10.80, 'seasoning'),
    (@recipe_yuxiang, @ing_cornstarch, '10', 'g', '腌制', 1, 0, NULL, 38.10, 'seasoning'),
    (@recipe_yuxiang, @ing_cooking_oil, '18', 'g', '滑炒', 0, 0, NULL, 159.12, 'seasoning'),
    (@recipe_yuxiang, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 8: 麻婆豆腐
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '麻婆豆腐',
    '麻辣鲜香的川式麻婆豆腐，豆腐嫩滑入味。',
    'https://images.example.com/mapo_tofu.jpg',
    'https://videos.example.com/mapo_tofu.mp4',
    25, 2, 'medium', @cuisine_sichuan,
    480.00, 32.00, 18.00, 30.00
);
SET @recipe_mapo := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_mapo, 1, '准备',
    '嫩豆腐切块入盐水焯烫，猪肉剁成末，蒜姜切末，花椒碾碎备用。',
    6, '中火', JSON_ARRAY('砧板', '菜刀', '汤锅'),
    '焯烫可去豆腥且保持豆腐韧性。'
);
SET @step_mapo_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_mapo_1, @tool_board, '切块'),
    (@step_mapo_1, @tool_knife, '切块'),
    (@step_mapo_1, @tool_soup_pot, '焯烫');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_mapo, 2, '煸炒',
    '热锅下油，下猪肉末煸至出油，加入豆瓣酱、蒜姜末炒出红油。',
    4, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '豆瓣酱炒出红油是关键步骤。'
);
SET @step_mapo_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_mapo_2, @tool_wok, '煸炒'),
    (@step_mapo_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_mapo, 3, '收汁',
    '加入高汤或热水，放入豆腐煮沸后改小火焖煮5分钟，加入酱油、花椒粉并用水淀粉勾薄芡。',
    8, '小火', JSON_ARRAY('炒锅', '锅铲'),
    '翻动豆腐时动作轻柔避免碎裂。'
);
SET @step_mapo_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_mapo_3, @tool_wok, '焖煮'),
    (@step_mapo_3, @tool_spatula, '勾芡');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_mapo, @ing_soft_tofu, '400', 'g', '切块焯烫', 5, 1, NULL, 280.00, 'main'),
    (@recipe_mapo, @ing_pork_loin, '120', 'g', '剁末', 3, 0, NULL, 171.60, 'auxiliary'),
    (@recipe_mapo, @ing_douban, '25', 'g', '炒香', 1, 0, NULL, 46.25, 'seasoning'),
    (@recipe_mapo, @ing_garlic, '15', 'g', '切末', 2, 0, NULL, 22.35, 'seasoning'),
    (@recipe_mapo, @ing_ginger, '10', 'g', '切末', 2, 0, NULL, 8.00, 'seasoning'),
    (@recipe_mapo, @ing_sichuan_pepper, '4', 'g', '碾粉', 1, 0, NULL, 12.00, 'seasoning'),
    (@recipe_mapo, @ing_soy_sauce, '15', 'ml', '调味', 0, 0, NULL, 10.80, 'seasoning'),
    (@recipe_mapo, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_mapo, @ing_cooking_oil, '18', 'g', '煸炒', 0, 0, NULL, 159.12, 'seasoning'),
    (@recipe_mapo, @ing_cornstarch, '8', 'g', '勾芡', 0, 0, NULL, 30.48, 'seasoning');

-- Recipe 9: 番茄炒蛋
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '番茄炒蛋',
    '酸甜柔滑的番茄炒蛋，是经典家常速成菜。',
    'https://images.example.com/fanqie_chao_dan.jpg',
    'https://videos.example.com/fanqie_chao_dan.mp4',
    15, 2, 'easy', @cuisine_home,
    360.00, 22.00, 16.00, 24.00
);
SET @recipe_tomato_egg := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_tomato_egg, 1, '打蛋',
    '鸡蛋打散加入少许盐调味，番茄切块，小葱切段备用。',
    3, '常温', JSON_ARRAY('搅拌碗', '砧板', '菜刀'),
    '蛋液充分打匀更蓬松。'
);
SET @step_tomato_egg_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_tomato_egg_1, @tool_mix_bowl, '打蛋'),
    (@step_tomato_egg_1, @tool_board, '切块'),
    (@step_tomato_egg_1, @tool_knife, '切块');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_tomato_egg, 2, '炒蛋',
    '热锅冷油，倒入蛋液快速翻炒至半凝固，盛出备用。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '保持蛋液嫩滑，炒至六成熟即可。'
);
SET @step_tomato_egg_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_tomato_egg_2, @tool_wok, '炒蛋'),
    (@step_tomato_egg_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_tomato_egg, 3, '合炒',
    '锅内留底油，下番茄煸出汁水后加入白砂糖调味，倒回鸡蛋迅速翻炒，撒上小葱即可。',
    3, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '番茄炒出汁再回蛋，味道更融合。'
);
SET @step_tomato_egg_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_tomato_egg_3, @tool_wok, '翻炒'),
    (@step_tomato_egg_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_tomato_egg, @ing_egg, '4', '个', '打散', 2, 1, NULL, 572.00, 'main'),
    (@recipe_tomato_egg, @ing_tomato, '300', 'g', '切块', 2, 0, NULL, 54.00, 'auxiliary'),
    (@recipe_tomato_egg, @ing_scallion, '10', 'g', '切段', 1, 0, NULL, 3.20, 'auxiliary'),
    (@recipe_tomato_egg, @ing_sugar, '6', 'g', '调味', 0, 0, NULL, 23.22, 'seasoning'),
    (@recipe_tomato_egg, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_tomato_egg, @ing_cooking_oil, '16', 'g', '炒制', 0, 0, NULL, 141.44, 'seasoning');

-- Recipe 10: 酸辣土豆丝
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '酸辣土豆丝',
    '脆爽开胃的酸辣土豆丝，酸度与辣度兼备。',
    'https://images.example.com/suanla_tudousi.jpg',
    'https://videos.example.com/suanla_tudousi.mp4',
    18, 2, 'easy', @cuisine_home,
    240.00, 6.00, 40.00, 8.00
);
SET @recipe_suanla_potato := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_suanla_potato, 1, '切丝',
    '土豆切细丝后用冷水浸泡去淀粉，青椒切丝，蒜拍碎备用。',
    6, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '土豆丝浸泡可保持爽脆不粘连。'
);
SET @step_suanla_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_suanla_1, @tool_board, '切丝'),
    (@step_suanla_1, @tool_knife, '切丝'),
    (@step_suanla_1, @tool_mix_bowl, '浸泡');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_suanla_potato, 2, '炝锅',
    '热锅下油，放入干辣椒、花椒和蒜片炝香。',
    1, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '炝锅时间短，避免花椒炒糊。'
);
SET @step_suanla_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_suanla_2, @tool_wok, '炝锅'),
    (@step_suanla_2, @tool_spatula, '翻动');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_suanla_potato, 3, '快炒',
    '倒入沥干的土豆丝和青椒丝大火翻炒2分钟，淋入米醋和盐快速翻匀出锅。',
    3, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '最后淋醋可锁住酸香风味。'
);
SET @step_suanla_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_suanla_3, @tool_wok, '翻炒'),
    (@step_suanla_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_suanla_potato, @ing_potato, '400', 'g', '切丝浸泡', 6, 1, NULL, 308.00, 'main'),
    (@recipe_suanla_potato, @ing_green_pepper, '40', 'g', '切丝', 1, 0, NULL, 8.00, 'auxiliary'),
    (@recipe_suanla_potato, @ing_dried_chili, '6', 'g', '剪段', 1, 0, NULL, 9.00, 'seasoning'),
    (@recipe_suanla_potato, @ing_sichuan_pepper, '3', 'g', '备用', 0, 0, NULL, 9.00, 'seasoning'),
    (@recipe_suanla_potato, @ing_vinegar, '20', 'ml', '淋汁', 0, 0, NULL, 3.60, 'seasoning'),
    (@recipe_suanla_potato, @ing_garlic, '10', 'g', '拍碎', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_suanla_potato, @ing_salt, '4', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_suanla_potato, @ing_cooking_oil, '16', 'g', '煸炒', 0, 0, NULL, 141.44, 'seasoning');

-- Recipe 11: 蒜香鸡腿
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '蒜香鸡腿',
    '外酥里嫩的蒜香鸡腿，鲜香多汁。',
    'https://images.example.com/suanxiang_jitui.jpg',
    'https://videos.example.com/suanxiang_jitui.mp4',
    35, 2, 'medium', @cuisine_home,
    540.00, 44.00, 14.00, 34.00
);
SET @recipe_garlic_chicken_thigh := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_garlic_chicken_thigh, 1, '腌制',
    '鸡腿肉去骨切块，加入蒜末、酱油、白砂糖和淀粉抓匀腌制15分钟。',
    15, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '腌制时加入少许淀粉，肉质更嫩滑。'
);
SET @step_garlic_chicken_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_garlic_chicken_1, @tool_board, '去骨'),
    (@step_garlic_chicken_1, @tool_knife, '切块'),
    (@step_garlic_chicken_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_garlic_chicken_thigh, 2, '煎制',
    '平底锅中倒油烧热，将鸡腿肉皮朝下煎至金黄后翻面煎熟。',
    8, '中火', JSON_ARRAY('平底锅', '锅铲'),
    '先煎带皮面，可逼出鸡油使外皮更酥。'
);
SET @step_garlic_chicken_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_garlic_chicken_2, @tool_flat_pan, '煎制'),
    (@step_garlic_chicken_2, @tool_spatula, '翻面');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_garlic_chicken_thigh, 3, '收汁',
    '加入少量清水，撒入蒜末快速翻匀收汁，装盘即可。',
    2, '大火', JSON_ARRAY('平底锅', '锅铲'),
    '收汁时保持大火，汁浓味更足。'
);
SET @step_garlic_chicken_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_garlic_chicken_3, @tool_flat_pan, '收汁'),
    (@step_garlic_chicken_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_garlic_chicken_thigh, @ing_chicken_leg, '400', 'g', '去骨切块', 10, 1, NULL, 708.00, 'main'),
    (@recipe_garlic_chicken_thigh, @ing_garlic, '20', 'g', '切末', 3, 0, NULL, 29.80, 'seasoning'),
    (@recipe_garlic_chicken_thigh, @ing_soy_sauce, '20', 'ml', '腌制', 1, 0, NULL, 14.40, 'seasoning'),
    (@recipe_garlic_chicken_thigh, @ing_sugar, '10', 'g', '腌制', 0, 0, NULL, 38.70, 'seasoning'),
    (@recipe_garlic_chicken_thigh, @ing_cornstarch, '10', 'g', '腌制', 1, 0, NULL, 38.10, 'seasoning'),
    (@recipe_garlic_chicken_thigh, @ing_cooking_oil, '18', 'g', '煎制', 0, 0, NULL, 159.12, 'seasoning'),
    (@recipe_garlic_chicken_thigh, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 12: 黑椒牛柳
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '黑椒牛柳',
    '黑胡椒香气浓郁的快炒牛柳，肉质鲜嫩。',
    'https://images.example.com/heijiao_niuliu.jpg',
    'https://videos.example.com/heijiao_niuliu.mp4',
    25, 2, 'medium', @cuisine_home,
    510.00, 42.00, 20.00, 26.00
);
SET @recipe_blackpepper_beef := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_blackpepper_beef, 1, '切配',
    '牛里脊切条，加入黑胡椒、酱油、淀粉腌制；洋葱、青椒切条备用。',
    6, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '牛柳逆纹切条，口感更嫩。'
);
SET @step_blackpepper_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_blackpepper_1, @tool_board, '切条'),
    (@step_blackpepper_1, @tool_knife, '切条'),
    (@step_blackpepper_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_blackpepper_beef, 2, '滑炒',
    '热锅下油，将牛柳快速滑散至变色即盛出。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '滑炒时间短，保持牛柳嫩度。'
);
SET @step_blackpepper_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_blackpepper_2, @tool_wok, '滑炒'),
    (@step_blackpepper_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_blackpepper_beef, 3, '合炒',
    '锅内留底油，下洋葱与青椒炒香，倒入牛柳、黑胡椒碎和调味料快速翻匀出锅。',
    3, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '最后可加少许清水勾薄芡锁住汁水。'
);
SET @step_blackpepper_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_blackpepper_3, @tool_wok, '翻炒'),
    (@step_blackpepper_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_blackpepper_beef, @ing_beef_tenderloin, '300', 'g', '切条腌制', 6, 1, NULL, 573.00, 'main'),
    (@recipe_blackpepper_beef, @ing_onion, '80', 'g', '切条', 2, 0, NULL, 32.00, 'auxiliary'),
    (@recipe_blackpepper_beef, @ing_green_pepper, '60', 'g', '切条', 2, 0, NULL, 12.00, 'auxiliary'),
    (@recipe_blackpepper_beef, @ing_black_pepper, '6', 'g', '压碎', 1, 0, NULL, 15.30, 'seasoning'),
    (@recipe_blackpepper_beef, @ing_soy_sauce, '18', 'ml', '调味', 0, 0, NULL, 12.96, 'seasoning'),
    (@recipe_blackpepper_beef, @ing_sugar, '6', 'g', '调味', 0, 0, NULL, 23.22, 'seasoning'),
    (@recipe_blackpepper_beef, @ing_cornstarch, '10', 'g', '腌制', 1, 0, NULL, 38.10, 'seasoning'),
    (@recipe_blackpepper_beef, @ing_cooking_oil, '16', 'g', '滑炒', 0, 0, NULL, 141.44, 'seasoning'),
    (@recipe_blackpepper_beef, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 13: 香菇小白菜
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '香菇小白菜',
    '爽口小白菜配香菇鲜味，清淡不寡淡。',
    'https://images.example.com/xianggu_xiaobaicai.jpg',
    'https://videos.example.com/xianggu_xiaobaicai.mp4',
    15, 2, 'easy', @cuisine_home,
    160.00, 10.00, 14.00, 6.00
);
SET @recipe_mushroom_greens := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_mushroom_greens, 1, '焯烫',
    '小白菜洗净切段，香菇去根切片，入沸水焯烫30秒后迅速过凉水。',
    2, '大火', JSON_ARRAY('汤锅'),
    '焯烫时间短，可保持脆嫩口感。'
);
SET @step_mushroom_greens_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_mushroom_greens_1, @tool_soup_pot, '焯烫');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_mushroom_greens, 2, '快炒',
    '热锅倒油，下蒜末爆香，倒入香菇与小白菜快速翻炒，加入蚝油调味。',
    3, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '快速翻炒让菜叶保持亮泽。'
);
SET @step_mushroom_greens_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_mushroom_greens_2, @tool_wok, '翻炒'),
    (@step_mushroom_greens_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_mushroom_greens, 3, '调味',
    '加入盐，淋入香油翻匀即可出锅。',
    1, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '香油最后加入能锁住香气。'
);
SET @step_mushroom_greens_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_mushroom_greens_3, @tool_wok, '翻炒'),
    (@step_mushroom_greens_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_mushroom_greens, @ing_bok_choy, '250', 'g', '切段焯烫', 3, 1, NULL, 32.50, 'main'),
    (@recipe_mushroom_greens, @ing_shiitake, '100', 'g', '切片', 2, 0, NULL, 34.00, 'auxiliary'),
    (@recipe_mushroom_greens, @ing_garlic, '10', 'g', '切末', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_mushroom_greens, @ing_oyster_sauce, '12', 'g', '调味', 0, 0, NULL, 8.64, 'seasoning'),
    (@recipe_mushroom_greens, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_mushroom_greens, @ing_cooking_oil, '12', 'g', '翻炒', 0, 0, NULL, 106.08, 'seasoning'),
    (@recipe_mushroom_greens, @ing_sesame_oil, '6', 'ml', '提香', 0, 0, NULL, 53.04, 'seasoning');

-- Recipe 14: 虾仁玉米粒
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '虾仁玉米粒',
    '色彩鲜艳的虾仁玉米粒，营养均衡。',
    'https://images.example.com/xiaoren_yumili.jpg',
    'https://videos.example.com/xiaoren_yumili.mp4',
    18, 2, 'easy', @cuisine_home,
    320.00, 28.00, 26.00, 12.00
);
SET @recipe_shrimp_corn := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_shrimp_corn, 1, '准备',
    '虾仁去虾线，用少许盐和淀粉抓匀；玉米粒、青豆、胡萝卜丁焯水备用。',
    4, '中火', JSON_ARRAY('砧板', '菜刀', '汤锅'),
    '焯水可以保持食材色泽鲜亮。'
);
SET @step_shrimp_corn_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_shrimp_corn_1, @tool_board, '处理'),
    (@step_shrimp_corn_1, @tool_knife, '切丁'),
    (@step_shrimp_corn_1, @tool_soup_pot, '焯水');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_shrimp_corn, 2, '滑炒',
    '热锅下油，放入虾仁快速滑炒至变色盛出。',
    1, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '虾仁刚变色就要盛出，避免过熟。'
);
SET @step_shrimp_corn_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_shrimp_corn_2, @tool_wok, '滑炒'),
    (@step_shrimp_corn_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_shrimp_corn, 3, '合炒',
    '锅内留底油，下玉米粒、青豆与胡萝卜丁翻炒1分钟，加入虾仁和调味料翻匀即可出锅。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '可加入少许清水勾薄芡让口感更润。'
);
SET @step_shrimp_corn_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_shrimp_corn_3, @tool_wok, '翻炒'),
    (@step_shrimp_corn_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_shrimp_corn, @ing_shrimp, '200', 'g', '去虾线腌制', 4, 1, NULL, 190.00, 'main'),
    (@recipe_shrimp_corn, @ing_corn_kernel, '120', 'g', '焯水', 2, 0, NULL, 103.20, 'auxiliary'),
    (@recipe_shrimp_corn, @ing_green_pea, '80', 'g', '焯水', 2, 0, NULL, 94.40, 'auxiliary'),
    (@recipe_shrimp_corn, @ing_carrot, '60', 'g', '切丁焯水', 2, 0, NULL, 24.60, 'auxiliary'),
    (@recipe_shrimp_corn, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_shrimp_corn, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_shrimp_corn, @ing_cooking_oil, '14', 'g', '滑炒', 0, 0, NULL, 123.76, 'seasoning'),
    (@recipe_shrimp_corn, @ing_cornstarch, '6', 'g', '腌制', 1, 0, NULL, 22.86, 'seasoning');

-- Recipe 15: 蒜蓉粉丝蒸虾
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '蒜蓉粉丝蒸虾',
    '蒜香浓郁的粉丝蒸虾，鲜美清爽。',
    'https://images.example.com/suanrong_fensi_zhengxia.jpg',
    'https://videos.example.com/suanrong_fensi_zhengxia.mp4',
    22, 2, 'easy', @cuisine_cantonese,
    280.00, 28.00, 24.00, 10.00
);
SET @recipe_steamed_shrimp_vermicelli := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_steamed_shrimp_vermicelli, 1, '泡粉丝',
    '粉丝用温水泡软沥干，虾仁去虾线备用。',
    6, '常温', JSON_ARRAY('搅拌碗'),
    '粉丝不要泡太久，保持弹性。'
);
SET @step_shrimp_vermicelli_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_shrimp_vermicelli_1, @tool_mix_bowl, '泡发');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_steamed_shrimp_vermicelli, 2, '调蒜蓉',
    '蒜末与酱油、香油拌匀铺在粉丝上，再摆入虾仁。',
    3, '常温', JSON_ARRAY('搅拌碗'),
    '蒜蓉铺匀能让虾仁均匀入味。'
);
SET @step_shrimp_vermicelli_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_shrimp_vermicelli_2, @tool_mix_bowl, '调味');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_steamed_shrimp_vermicelli, 3, '蒸制',
    '蒸锅水开后入锅，大火蒸8分钟，取出撒盐即可。',
    8, '大火', JSON_ARRAY('蒸锅'),
    '蒸制时间依虾大小微调，保持鲜嫩。'
);
SET @step_shrimp_vermicelli_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_shrimp_vermicelli_3, @tool_steamer, '蒸制');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_steamed_shrimp_vermicelli, @ing_shrimp, '220', 'g', '去虾线', 4, 1, NULL, 209.00, 'main'),
    (@recipe_steamed_shrimp_vermicelli, @ing_vermicelli, '80', 'g', '泡软', 6, 0, NULL, 265.60, 'auxiliary'),
    (@recipe_steamed_shrimp_vermicelli, @ing_garlic, '25', 'g', '切末', 2, 0, NULL, 37.25, 'seasoning'),
    (@recipe_steamed_shrimp_vermicelli, @ing_soy_sauce, '15', 'ml', '调味', 0, 0, NULL, 10.80, 'seasoning'),
    (@recipe_steamed_shrimp_vermicelli, @ing_sesame_oil, '8', 'ml', '调味', 0, 0, NULL, 70.72, 'seasoning'),
    (@recipe_steamed_shrimp_vermicelli, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 16: 清炒西葫芦
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '清炒西葫芦',
    '口感清爽的清炒西葫芦，低脂轻负担。',
    'https://images.example.com/qingchao_xihulu.jpg',
    'https://videos.example.com/qingchao_xihulu.mp4',
    12, 2, 'easy', @cuisine_home,
    180.00, 6.00, 16.00, 10.00
);
SET @recipe_sauteed_zucchini := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_sauteed_zucchini, 1, '切配',
    '西葫芦切薄片，胡萝卜切丝，蒜切片备用。',
    3, '常温', JSON_ARRAY('砧板', '菜刀'),
    '切片厚度一致，受热更均匀。'
);
SET @step_zucchini_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_zucchini_1, @tool_board, '切片'),
    (@step_zucchini_1, @tool_knife, '切配');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_sauteed_zucchini, 2, '爆香',
    '热锅下油，放入蒜片与胡萝卜丝炒香。',
    1, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '蒜片出香味即可，不可炒糊。'
);
SET @step_zucchini_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_zucchini_2, @tool_wok, '爆香'),
    (@step_zucchini_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_sauteed_zucchini, 3, '快炒',
    '倒入西葫芦片大火快炒2分钟，加入盐和白砂糖调味即可出锅。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '火力要大，保持西葫芦爽脆。'
);
SET @step_zucchini_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_zucchini_3, @tool_wok, '翻炒'),
    (@step_zucchini_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_sauteed_zucchini, @ing_zucchini, '300', 'g', '切片', 3, 1, NULL, 51.00, 'main'),
    (@recipe_sauteed_zucchini, @ing_carrot, '40', 'g', '切丝', 1, 0, NULL, 16.40, 'auxiliary'),
    (@recipe_sauteed_zucchini, @ing_garlic, '8', 'g', '切片', 1, 0, NULL, 11.92, 'seasoning'),
    (@recipe_sauteed_zucchini, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_sauteed_zucchini, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_sauteed_zucchini, @ing_cooking_oil, '14', 'g', '快炒', 0, 0, NULL, 123.76, 'seasoning');

-- Recipe 17: 柠檬蒸三文鱼
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '柠檬蒸三文鱼',
    '清爽低脂的柠檬蒸三文鱼，锁住鱼肉鲜嫩。',
    'https://images.example.com/ningmeng_zheng_sanwenyu.jpg',
    'https://videos.example.com/ningmeng_zheng_sanwenyu.mp4',
    25, 2, 'easy', @cuisine_cantonese,
    420.00, 38.00, 8.00, 26.00
);
SET @recipe_lemon_salmon := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_lemon_salmon, 1, '腌制',
    '三文鱼切块放入腌制碗，加入姜片、柠檬片、盐和香油轻轻抹匀腌制10分钟。',
    10, '常温', JSON_ARRAY('砧板', '菜刀', '腌制碗'),
    '柠檬片轻压出汁，腌制更入味。'
);
SET @step_lemon_salmon_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_lemon_salmon_1, @tool_board, '切块'),
    (@step_lemon_salmon_1, @tool_knife, '切块'),
    (@step_lemon_salmon_1, @tool_marinade_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_lemon_salmon, 2, '蒸制',
    '蒸锅水开后放入三文鱼，大火蒸8分钟。',
    8, '大火', JSON_ARRAY('蒸锅'),
    '蒸制时间依据鱼块厚度调整，保持嫩度。'
);
SET @step_lemon_salmon_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_lemon_salmon_2, @tool_steamer, '蒸制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_lemon_salmon, 3, '调味',
    '取出后淋少许香油，挤入柠檬汁即可享用。',
    1, '常温', JSON_ARRAY('腌制碗'),
    '蒸后调味更能保留柠檬清香。'
);
SET @step_lemon_salmon_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_lemon_salmon_3, @tool_marinade_bowl, '调味');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_lemon_salmon, @ing_salmon, '280', 'g', '切块腌制', 10, 1, NULL, 582.40, 'main'),
    (@recipe_lemon_salmon, @ing_lemon, '1', '个', '切片挤汁', 2, 0, NULL, 29.00, 'auxiliary'),
    (@recipe_lemon_salmon, @ing_ginger, '10', 'g', '切片', 1, 0, NULL, 8.00, 'seasoning'),
    (@recipe_lemon_salmon, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_lemon_salmon, @ing_sesame_oil, '6', 'ml', '调味', 0, 0, NULL, 53.04, 'seasoning'),
    (@recipe_lemon_salmon, @ing_cooking_oil, '12', 'g', '抹油', 0, 0, NULL, 106.08, 'seasoning');

-- Recipe 18: 豆豉蒸排骨
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '豆豉蒸排骨',
    '经典广式豆豉蒸排骨，鲜香入味带回甘。',
    'https://images.example.com/douchi_zheng_paigu.jpg',
    'https://videos.example.com/douchi_zheng_paigu.mp4',
    35, 2, 'medium', @cuisine_cantonese,
    620.00, 42.00, 18.00, 38.00
);
SET @recipe_blackbean_ribs := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_blackbean_ribs, 1, '腌制',
    '排骨切小段，加入豆豉、蒜末、酱油、白砂糖、蚝油抓匀腌制15分钟。',
    15, '常温', JSON_ARRAY('砧板', '菜刀', '腌制碗'),
    '腌制时可加入少许淀粉锁汁。'
);
SET @step_blackbean_ribs_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_blackbean_ribs_1, @tool_board, '切段'),
    (@step_blackbean_ribs_1, @tool_knife, '切段'),
    (@step_blackbean_ribs_1, @tool_marinade_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_blackbean_ribs, 2, '蒸制',
    '蒸锅水开后，将排骨连同腌汁一起放入蒸盘，大火蒸18分钟。',
    18, '大火', JSON_ARRAY('蒸锅'),
    '蒸至排骨轻易脱骨即可。'
);
SET @step_blackbean_ribs_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_blackbean_ribs_2, @tool_steamer, '蒸制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_blackbean_ribs, 3, '调味',
    '出锅后撒上葱花或少许香油提香即可食用。',
    1, '常温', JSON_ARRAY('腌制碗'),
    '可适量调入盐调节咸度。'
);
SET @step_blackbean_ribs_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_blackbean_ribs_3, @tool_marinade_bowl, '调味');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_blackbean_ribs, @ing_pork_ribs, '450', 'g', '切段腌制', 10, 1, NULL, 720.00, 'main'),
    (@recipe_blackbean_ribs, @ing_fermented_black_bean, '20', 'g', '剁碎', 1, 0, NULL, 40.00, 'seasoning'),
    (@recipe_blackbean_ribs, @ing_garlic, '15', 'g', '切末', 2, 0, NULL, 22.35, 'seasoning'),
    (@recipe_blackbean_ribs, @ing_soy_sauce, '15', 'ml', '腌制', 0, 0, NULL, 10.80, 'seasoning'),
    (@recipe_blackbean_ribs, @ing_sugar, '8', 'g', '腌制', 0, 0, NULL, 30.96, 'seasoning'),
    (@recipe_blackbean_ribs, @ing_oyster_sauce, '10', 'g', '腌制', 0, 0, NULL, 7.20, 'seasoning'),
    (@recipe_blackbean_ribs, @ing_cooking_oil, '10', 'g', '腌制', 0, 0, NULL, 88.40, 'seasoning'),
    (@recipe_blackbean_ribs, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 19: 家常豆腐
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '家常豆腐',
    '香辣下饭的家常豆腐，豆腐外焦里嫩。',
    'https://images.example.com/jiachang_doufu.jpg',
    'https://videos.example.com/jiachang_doufu.mp4',
    28, 2, 'medium', @cuisine_home,
    520.00, 32.00, 26.00, 30.00
);
SET @recipe_home_tofu := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_home_tofu, 1, '准备',
    '嫩豆腐切厚片入盐水焯烫，捞出沥干；猪肉切薄片，青椒胡萝卜切条。',
    6, '中火', JSON_ARRAY('砧板', '菜刀', '汤锅'),
    '焯烫可去豆腥并增强豆腐韧性。'
);
SET @step_home_tofu_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_home_tofu_1, @tool_board, '切块'),
    (@step_home_tofu_1, @tool_knife, '切片'),
    (@step_home_tofu_1, @tool_soup_pot, '焯烫');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_home_tofu, 2, '煎豆腐',
    '平底锅加少许油，将豆腐煎至两面金黄取出。',
    4, '中火', JSON_ARRAY('平底锅', '锅铲'),
    '煎制过程中轻推豆腐，避免粘锅。'
);
SET @step_home_tofu_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_home_tofu_2, @tool_flat_pan, '煎制'),
    (@step_home_tofu_2, @tool_spatula, '翻面');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_home_tofu, 3, '合炒',
    '热锅下油炒香豆瓣酱、蒜末，加入猪肉片翻炒变色，再放入豆腐、青椒、胡萝卜，加入酱油和少许水焖煮2分钟。',
    6, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '翻动豆腐时动作轻，保持完整。'
);
SET @step_home_tofu_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_home_tofu_3, @tool_wok, '翻炒'),
    (@step_home_tofu_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_home_tofu, @ing_soft_tofu, '400', 'g', '切片焯烫', 4, 1, NULL, 280.00, 'main'),
    (@recipe_home_tofu, @ing_pork_loin, '120', 'g', '切片', 3, 0, NULL, 171.60, 'auxiliary'),
    (@recipe_home_tofu, @ing_green_pepper, '60', 'g', '切条', 2, 0, NULL, 12.00, 'auxiliary'),
    (@recipe_home_tofu, @ing_carrot, '50', 'g', '切条', 1, 0, NULL, 20.50, 'auxiliary'),
    (@recipe_home_tofu, @ing_douban, '15', 'g', '炒香', 1, 0, NULL, 27.75, 'seasoning'),
    (@recipe_home_tofu, @ing_garlic, '12', 'g', '切末', 1, 0, NULL, 17.88, 'seasoning'),
    (@recipe_home_tofu, @ing_soy_sauce, '18', 'ml', '调味', 0, 0, NULL, 12.96, 'seasoning'),
    (@recipe_home_tofu, @ing_cornstarch, '6', 'g', '勾芡', 0, 0, NULL, 22.86, 'seasoning'),
    (@recipe_home_tofu, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_home_tofu, @ing_cooking_oil, '18', 'g', '煎炒', 0, 0, NULL, 159.12, 'seasoning');

-- Recipe 20: 椒香虾仁
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '椒香虾仁',
    '椒麻清香的虾仁小炒，鲜嫩爽口。',
    'https://images.example.com/jiaoxiang_xiaren.jpg',
    'https://videos.example.com/jiaoxiang_xiaren.mp4',
    16, 2, 'easy', @cuisine_sichuan,
    300.00, 26.00, 10.00, 14.00
);
SET @recipe_pepper_shrimp := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pepper_shrimp, 1, '腌制',
    '虾仁加入酱油、黑胡椒碎、淀粉抓匀腌制10分钟。',
    10, '常温', JSON_ARRAY('搅拌碗'),
    '腌制时加入少许香油提升香气。'
);
SET @step_pepper_shrimp_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pepper_shrimp_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pepper_shrimp, 2, '炝锅',
    '热锅下油，加入干辣椒与花椒小火炒香，再放入蒜姜末。',
    1, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '炝锅时火力不宜过大，避免焦糊。'
);
SET @step_pepper_shrimp_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pepper_shrimp_2, @tool_wok, '炝锅'),
    (@step_pepper_shrimp_2, @tool_spatula, '翻动');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pepper_shrimp, 3, '快炒',
    '倒入虾仁大火快炒至变色，加入酱油、香油、白砂糖调味，快速翻匀即可。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '炒制时间短，虾仁保持弹嫩。'
);
SET @step_pepper_shrimp_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pepper_shrimp_3, @tool_wok, '翻炒'),
    (@step_pepper_shrimp_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_pepper_shrimp, @ing_shrimp, '240', 'g', '腌制', 10, 1, NULL, 216.00, 'main'),
    (@recipe_pepper_shrimp, @ing_dried_chili, '6', 'g', '剪段', 1, 0, NULL, 9.00, 'seasoning'),
    (@recipe_pepper_shrimp, @ing_sichuan_pepper, '3', 'g', '备用', 0, 0, NULL, 9.00, 'seasoning'),
    (@recipe_pepper_shrimp, @ing_garlic, '10', 'g', '切末', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_pepper_shrimp, @ing_ginger, '8', 'g', '切末', 1, 0, NULL, 6.40, 'seasoning'),
    (@recipe_pepper_shrimp, @ing_black_pepper, '4', 'g', '腌制', 0, 0, NULL, 10.20, 'seasoning'),
    (@recipe_pepper_shrimp, @ing_soy_sauce, '12', 'ml', '调味', 0, 0, NULL, 8.64, 'seasoning'),
    (@recipe_pepper_shrimp, @ing_sesame_oil, '6', 'ml', '调味', 0, 0, NULL, 53.04, 'seasoning'),
    (@recipe_pepper_shrimp, @ing_cooking_oil, '16', 'g', '爆香', 0, 0, NULL, 141.44, 'seasoning'),
    (@recipe_pepper_shrimp, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_pepper_shrimp, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

COMMIT;

-- Recipe 21: 姜葱牛肉
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '姜葱牛肉',
    '姜葱爆香的滑嫩牛肉，咸鲜带微辣，是经典粤式家常菜。',
    'https://images.example.com/jiangcong_niurou.jpg',
    'https://videos.example.com/jiangcong_niurou.mp4',
    22, 2, 'medium', @cuisine_home,
    520.00, 42.00, 16.00, 28.00
);
SET @recipe_ginger_beef := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_ginger_beef, 1, '切配',
    '牛里脊逆纹切条加入酱油、黑胡椒、玉米淀粉和香油抓匀腌制；姜切丝，葱切段。',
    6, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '腌制时加入少量香油可锁住肉汁。'
);
SET @step_ginger_beef_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_ginger_beef_1, @tool_board, '切条'),
    (@step_ginger_beef_1, @tool_knife, '切条'),
    (@step_ginger_beef_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_ginger_beef, 2, '滑炒',
    '热锅倒油，下牛柳快速滑炒至变色即盛出。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '滑炒时间不超过1分钟，保持牛肉嫩度。'
);
SET @step_ginger_beef_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_ginger_beef_2, @tool_wok, '滑炒'),
    (@step_ginger_beef_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_ginger_beef, 3, '合炒',
    '锅内留油，下姜丝爆香，放入牛柳、葱段快速翻炒，调入酱油和盐即可出锅。',
    3, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '葱段后下保持脆爽口感。'
);
SET @step_ginger_beef_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_ginger_beef_3, @tool_wok, '翻炒'),
    (@step_ginger_beef_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_ginger_beef, @ing_beef_tenderloin, '320', 'g', '切条腌制', 6, 1, NULL, 611.20, 'main'),
    (@recipe_ginger_beef, @ing_ginger, '15', 'g', '切丝', 2, 0, NULL, 12.00, 'seasoning'),
    (@recipe_ginger_beef, @ing_scallion, '20', 'g', '切段', 1, 0, NULL, 6.40, 'auxiliary'),
    (@recipe_ginger_beef, @ing_soy_sauce, '20', 'ml', '腌制/调味', 0, 0, NULL, 14.40, 'seasoning'),
    (@recipe_ginger_beef, @ing_black_pepper, '5', 'g', '碾碎', 1, 0, NULL, 12.75, 'seasoning'),
    (@recipe_ginger_beef, @ing_cornstarch, '12', 'g', '腌制', 1, 0, NULL, 45.72, 'seasoning'),
    (@recipe_ginger_beef, @ing_sesame_oil, '6', 'ml', '腌制', 0, 0, NULL, 53.04, 'seasoning'),
    (@recipe_ginger_beef, @ing_cooking_oil, '18', 'g', '炒制', 0, 0, NULL, 159.12, 'seasoning'),
    (@recipe_ginger_beef, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 22: 双椒鸡丁
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '双椒鸡丁',
    '青红双椒搭配鸡丁，口感清爽带点微辣。',
    'https://images.example.com/shuangjiao_jiding.jpg',
    'https://videos.example.com/shuangjiao_jiding.mp4',
    20, 2, 'easy', @cuisine_home,
    430.00, 36.00, 18.00, 20.00
);
SET @recipe_two_pepper_chicken := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_two_pepper_chicken, 1, '腌制',
    '鸡胸肉切丁加入酱油、玉米淀粉和香油抓匀；青椒、干辣椒切块，蒜姜切末。',
    5, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '腌制时少量香油能让鸡丁更滑嫩。'
);
SET @step_two_pepper_chicken_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_two_pepper_chicken_1, @tool_board, '切丁'),
    (@step_two_pepper_chicken_1, @tool_knife, '切丁'),
    (@step_two_pepper_chicken_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_two_pepper_chicken, 2, '滑炒',
    '热锅倒油，下鸡丁快速滑散炒至变白盛出。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '滑炒时不断翻动避免粘锅。'
);
SET @step_two_pepper_chicken_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_two_pepper_chicken_2, @tool_wok, '滑炒'),
    (@step_two_pepper_chicken_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_two_pepper_chicken, 3, '合炒',
    '锅内留底油，下蒜姜末、干辣椒煸香，倒入青椒块与鸡丁，调入酱油、白砂糖和米醋快速翻炒。',
    3, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '出锅前淋少许米醋提味即可。'
);
SET @step_two_pepper_chicken_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_two_pepper_chicken_3, @tool_wok, '翻炒'),
    (@step_two_pepper_chicken_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_two_pepper_chicken, @ing_chicken, '320', 'g', '切丁腌制', 5, 1, NULL, 512.00, 'main'),
    (@recipe_two_pepper_chicken, @ing_green_pepper, '120', 'g', '切块', 2, 0, NULL, 24.00, 'auxiliary'),
    (@recipe_two_pepper_chicken, @ing_dried_chili, '10', 'g', '剪段', 1, 0, NULL, 15.00, 'seasoning'),
    (@recipe_two_pepper_chicken, @ing_garlic, '15', 'g', '切末', 2, 0, NULL, 22.35, 'seasoning'),
    (@recipe_two_pepper_chicken, @ing_ginger, '10', 'g', '切末', 1, 0, NULL, 8.00, 'seasoning'),
    (@recipe_two_pepper_chicken, @ing_soy_sauce, '18', 'ml', '调味', 0, 0, NULL, 12.96, 'seasoning'),
    (@recipe_two_pepper_chicken, @ing_sugar, '6', 'g', '调味', 0, 0, NULL, 23.22, 'seasoning'),
    (@recipe_two_pepper_chicken, @ing_vinegar, '8', 'ml', '提味', 0, 0, NULL, 1.44, 'seasoning'),
    (@recipe_two_pepper_chicken, @ing_cornstarch, '12', 'g', '腌制', 1, 0, NULL, 45.72, 'seasoning'),
    (@recipe_two_pepper_chicken, @ing_sesame_oil, '6', 'ml', '腌制', 0, 0, NULL, 53.04, 'seasoning'),
    (@recipe_two_pepper_chicken, @ing_cooking_oil, '16', 'g', '炒制', 0, 0, NULL, 141.44, 'seasoning'),
    (@recipe_two_pepper_chicken, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 23: 西兰花虾仁
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '西兰花虾仁',
    '清爽低脂的西兰花虾仁，小炒操作简单营养均衡。',
    'https://images.example.com/xilanhua_xiaren.jpg',
    'https://videos.example.com/xilanhua_xiaren.mp4',
    18, 2, 'easy', @cuisine_home,
    280.00, 28.00, 20.00, 10.00
);
SET @recipe_broccoli_shrimp := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_broccoli_shrimp, 1, '焯烫',
    '西兰花掰小朵焯水后过凉，虾仁去虾线用盐和玉米淀粉抓匀。',
    4, '大火', JSON_ARRAY('汤锅', '搅拌碗'),
    '焯烫时间控制在1分钟，保持翠绿脆嫩。'
);
SET @step_broccoli_shrimp_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_broccoli_shrimp_1, @tool_soup_pot, '焯烫'),
    (@step_broccoli_shrimp_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_broccoli_shrimp, 2, '滑炒',
    '热锅少油滑炒虾仁至变色盛出。',
    1, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '虾仁刚变色立刻盛出避免过老。'
);
SET @step_broccoli_shrimp_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_broccoli_shrimp_2, @tool_wok, '滑炒'),
    (@step_broccoli_shrimp_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_broccoli_shrimp, 3, '合炒',
    '锅内留油，下蒜末炒香，倒入西兰花和虾仁，加盐、白砂糖和香油翻炒均匀。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '最后淋香油提升香气即可出锅。'
);
SET @step_broccoli_shrimp_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_broccoli_shrimp_3, @tool_wok, '翻炒'),
    (@step_broccoli_shrimp_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_broccoli_shrimp, @ing_shrimp, '220', 'g', '腌制', 3, 1, NULL, 209.00, 'main'),
    (@recipe_broccoli_shrimp, @ing_broccoli, '260', 'g', '焯烫', 3, 0, NULL, 88.40, 'auxiliary'),
    (@recipe_broccoli_shrimp, @ing_garlic, '12', 'g', '切末', 1, 0, NULL, 17.88, 'seasoning'),
    (@recipe_broccoli_shrimp, @ing_cornstarch, '8', 'g', '腌制', 1, 0, NULL, 30.48, 'seasoning'),
    (@recipe_broccoli_shrimp, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_broccoli_shrimp, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_broccoli_shrimp, @ing_sesame_oil, '6', 'ml', '提香', 0, 0, NULL, 53.04, 'seasoning'),
    (@recipe_broccoli_shrimp, @ing_cooking_oil, '14', 'g', '滑炒', 0, 0, NULL, 123.76, 'seasoning');

-- Recipe 24: 玉米青豆鸡丁
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '玉米青豆鸡丁',
    '玉米青豆与鸡丁同炒，甜嫩爽脆，色彩丰富。',
    'https://images.example.com/yumi_qingdou_jiding.jpg',
    'https://videos.example.com/yumi_qingdou_jiding.mp4',
    18, 2, 'easy', @cuisine_home,
    420.00, 34.00, 28.00, 18.00
);
SET @recipe_corn_pea_chicken := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_corn_pea_chicken, 1, '腌制',
    '鸡胸肉切小丁加入酱油、玉米淀粉腌制；玉米粒、青豆、胡萝卜丁焯水备用，蒜切末。',
    5, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗', '汤锅'),
    '玉米青豆提前焯水可缩短炒制时间。'
);
SET @step_corn_pea_chicken_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_corn_pea_chicken_1, @tool_board, '切丁'),
    (@step_corn_pea_chicken_1, @tool_knife, '切丁'),
    (@step_corn_pea_chicken_1, @tool_mix_bowl, '腌制'),
    (@step_corn_pea_chicken_1, @tool_soup_pot, '焯水');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_corn_pea_chicken, 2, '滑炒',
    '热锅少油滑炒鸡丁至九成熟盛出。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '滑炒至表面金白即可，不用过熟。'
);
SET @step_corn_pea_chicken_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_corn_pea_chicken_2, @tool_wok, '滑炒'),
    (@step_corn_pea_chicken_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_corn_pea_chicken, 3, '合炒',
    '锅中留油，下蒜末炒香，倒入玉米粒、青豆、胡萝卜丁和鸡丁，调入盐、白砂糖和酱油快速翻匀。',
    3, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '可加少许水淀粉勾薄芡使鸡丁更润。'
);
SET @step_corn_pea_chicken_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_corn_pea_chicken_3, @tool_wok, '翻炒'),
    (@step_corn_pea_chicken_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_corn_pea_chicken, @ing_chicken, '300', 'g', '切丁腌制', 5, 1, NULL, 480.00, 'main'),
    (@recipe_corn_pea_chicken, @ing_corn_kernel, '120', 'g', '焯水', 2, 0, NULL, 103.20, 'auxiliary'),
    (@recipe_corn_pea_chicken, @ing_green_pea, '90', 'g', '焯水', 2, 0, NULL, 106.20, 'auxiliary'),
    (@recipe_corn_pea_chicken, @ing_carrot, '60', 'g', '切丁焯水', 2, 0, NULL, 24.60, 'auxiliary'),
    (@recipe_corn_pea_chicken, @ing_garlic, '10', 'g', '切末', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_corn_pea_chicken, @ing_soy_sauce, '16', 'ml', '调味', 0, 0, NULL, 11.52, 'seasoning'),
    (@recipe_corn_pea_chicken, @ing_sugar, '5', 'g', '调味', 0, 0, NULL, 19.35, 'seasoning'),
    (@recipe_corn_pea_chicken, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_corn_pea_chicken, @ing_cornstarch, '10', 'g', '腌制', 1, 0, NULL, 38.10, 'seasoning'),
    (@recipe_corn_pea_chicken, @ing_cooking_oil, '15', 'g', '炒制', 0, 0, NULL, 132.60, 'seasoning');

-- Recipe 25: 豆瓣烧土豆
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '豆瓣烧土豆',
    '郫县豆瓣酱慢炖土豆，辣香浓稠，非常下饭。',
    'https://images.example.com/douban_shaotudou.jpg',
    'https://videos.example.com/douban_shaotudou.mp4',
    28, 2, 'easy', @cuisine_sichuan,
    360.00, 10.00, 54.00, 12.00
);
SET @recipe_douban_potato := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_douban_potato, 1, '切配',
    '土豆去皮切滚刀块用清水泡去淀粉，胡萝卜切块，蒜姜切末。',
    5, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '泡水可避免氧化并去除多余淀粉。'
);
SET @step_douban_potato_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_douban_potato_1, @tool_board, '切块'),
    (@step_douban_potato_1, @tool_knife, '切块'),
    (@step_douban_potato_1, @tool_mix_bowl, '浸泡');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_douban_potato, 2, '煸炒',
    '热锅下油，爆香蒜姜末和豆瓣酱，加入土豆、胡萝卜翻炒均匀。',
    4, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '豆瓣酱先炒出红油，菜品更香。'
);
SET @step_douban_potato_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_douban_potato_2, @tool_wok, '煸炒'),
    (@step_douban_potato_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_douban_potato, 3, '焖煮',
    '倒入清水没过食材，加入酱油、白砂糖和盐，小火焖煮15分钟收汁即可。',
    15, '小火', JSON_ARRAY('炒锅', '锅铲'),
    '焖煮至汤汁浓稠能够充分裹住土豆。'
);
SET @step_douban_potato_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_douban_potato_3, @tool_wok, '焖煮'),
    (@step_douban_potato_3, @tool_spatula, '收汁');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_douban_potato, @ing_potato, '400', 'g', '切块', 5, 1, NULL, 308.00, 'main'),
    (@recipe_douban_potato, @ing_carrot, '120', 'g', '切块', 2, 0, NULL, 49.20, 'auxiliary'),
    (@recipe_douban_potato, @ing_douban, '25', 'g', '炒香', 1, 0, NULL, 46.25, 'seasoning'),
    (@recipe_douban_potato, @ing_garlic, '12', 'g', '切末', 1, 0, NULL, 17.88, 'seasoning'),
    (@recipe_douban_potato, @ing_ginger, '10', 'g', '切末', 1, 0, NULL, 8.00, 'seasoning'),
    (@recipe_douban_potato, @ing_soy_sauce, '15', 'ml', '调味', 0, 0, NULL, 10.80, 'seasoning'),
    (@recipe_douban_potato, @ing_sugar, '6', 'g', '调味', 0, 0, NULL, 23.22, 'seasoning'),
    (@recipe_douban_potato, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_douban_potato, @ing_cooking_oil, '16', 'g', '煸炒', 0, 0, NULL, 141.44, 'seasoning');

-- Recipe 26: 小白菜豆腐汤
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '小白菜豆腐汤',
    '清淡温润的小白菜豆腐汤，适合搭配家常餐。',
    'https://images.example.com/xiaobaicai_doufutang.jpg',
    'https://videos.example.com/xiaobaicai_doufutang.mp4',
    15, 3, 'easy', @cuisine_home,
    160.00, 16.00, 8.00, 6.00
);
SET @recipe_bokchoy_tofu_soup := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_bokchoy_tofu_soup, 1, '准备',
    '小白菜洗净切段，嫩豆腐切片，香菇切丝，姜切片。',
    4, '常温', JSON_ARRAY('砧板', '菜刀'),
    '豆腐切片后用热水冲洗可去豆腥。'
);
SET @step_bokchoy_tofu_soup_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_bokchoy_tofu_soup_1, @tool_board, '切配'),
    (@step_bokchoy_tofu_soup_1, @tool_knife, '切配');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_bokchoy_tofu_soup, 2, '煸香',
    '汤锅内加少许油，下姜片和香菇丝略煸出香味。',
    1, '中火', JSON_ARRAY('汤锅'),
    '香菇煸香后汤味更鲜。'
);
SET @step_bokchoy_tofu_soup_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_bokchoy_tofu_soup_2, @tool_soup_pot, '煸香');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_bokchoy_tofu_soup, 3, '煮汤',
    '加入适量清水煮沸，放入豆腐和小白菜煮3分钟，加盐和香油调味即可。',
    3, '中火', JSON_ARRAY('汤锅'),
    '豆腐入锅后转小火避免碎裂。'
);
SET @step_bokchoy_tofu_soup_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_bokchoy_tofu_soup_3, @tool_soup_pot, '煮汤');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_bokchoy_tofu_soup, @ing_soft_tofu, '320', 'g', '切片', 3, 1, NULL, 224.00, 'main'),
    (@recipe_bokchoy_tofu_soup, @ing_bok_choy, '200', 'g', '切段', 2, 0, NULL, 26.00, 'auxiliary'),
    (@recipe_bokchoy_tofu_soup, @ing_shiitake, '60', 'g', '切丝', 2, 0, NULL, 20.40, 'auxiliary'),
    (@recipe_bokchoy_tofu_soup, @ing_ginger, '8', 'g', '切片', 1, 0, NULL, 6.40, 'seasoning'),
    (@recipe_bokchoy_tofu_soup, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_bokchoy_tofu_soup, @ing_sesame_oil, '5', 'ml', '调味', 0, 0, NULL, 44.20, 'seasoning'),
    (@recipe_bokchoy_tofu_soup, @ing_cooking_oil, '8', 'g', '煸香', 0, 0, NULL, 70.88, 'seasoning');

-- Recipe 27: 黑椒香煎三文鱼
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '黑椒香煎三文鱼',
    '黑胡椒与柠檬搭配煎制三文鱼，外焦里嫩。',
    'https://images.example.com/heijiao_pan_salmon.jpg',
    'https://videos.example.com/heijiao_pan_salmon.mp4',
    15, 2, 'easy', @cuisine_home,
    520.00, 40.00, 6.00, 32.00
);
SET @recipe_pan_seared_salmon := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pan_seared_salmon, 1, '腌制',
    '三文鱼擦干后抹上盐、黑胡椒、少许柠檬汁和香油腌制5分钟。',
    5, '常温', JSON_ARRAY('砧板', '菜刀', '腌制碗'),
    '腌制时间不宜过长，保持鱼肉水分。'
);
SET @step_pan_seared_salmon_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pan_seared_salmon_1, @tool_board, '处理'),
    (@step_pan_seared_salmon_1, @tool_knife, '处理'),
    (@step_pan_seared_salmon_1, @tool_marinade_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pan_seared_salmon, 2, '煎制',
    '平底锅热油，先将鱼皮面朝下煎至金黄，再翻面煎熟。',
    6, '中火', JSON_ARRAY('平底锅', '锅铲'),
    '煎制过程中轻轻压鱼皮可避免卷起。'
);
SET @step_pan_seared_salmon_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pan_seared_salmon_2, @tool_flat_pan, '煎制'),
    (@step_pan_seared_salmon_2, @tool_spatula, '翻面');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pan_seared_salmon, 3, '调味',
    '关火后淋上柠檬汁，撒上蒜末和少许香油增香。',
    1, '常温', JSON_ARRAY('平底锅'),
    '最后调味在余温下完成，保持蒜香。'
);
SET @step_pan_seared_salmon_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pan_seared_salmon_3, @tool_flat_pan, '调味');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_pan_seared_salmon, @ing_salmon, '260', 'g', '腌制', 5, 1, NULL, 541.60, 'main'),
    (@recipe_pan_seared_salmon, @ing_black_pepper, '4', 'g', '碾碎', 1, 0, NULL, 10.20, 'seasoning'),
    (@recipe_pan_seared_salmon, @ing_lemon, '1', '个', '榨汁', 1, 0, NULL, 29.00, 'auxiliary'),
    (@recipe_pan_seared_salmon, @ing_garlic, '8', 'g', '切末', 1, 0, NULL, 11.92, 'seasoning'),
    (@recipe_pan_seared_salmon, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_pan_seared_salmon, @ing_sesame_oil, '5', 'ml', '调味', 0, 0, NULL, 44.20, 'seasoning'),
    (@recipe_pan_seared_salmon, @ing_cooking_oil, '12', 'g', '煎制', 0, 0, NULL, 106.08, 'seasoning');

-- Recipe 28: 酱香猪里脊
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '酱香猪里脊',
    '猪里脊外酥里嫩，裹上甜辣豆瓣酱汁，非常下饭。',
    'https://images.example.com/jiangxiang_zhuliji.jpg',
    'https://videos.example.com/jiangxiang_zhuliji.mp4',
    25, 2, 'medium', @cuisine_home,
    520.00, 36.00, 26.00, 24.00
);
SET @recipe_saucy_pork := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_saucy_pork, 1, '腌制',
    '猪里脊切条加入酱油、玉米淀粉、绍兴酒腌10分钟；蒜末和豆瓣酱调成酱汁备用。',
    6, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '腌制后轻拍干淀粉可让外层更酥。'
);
SET @step_saucy_pork_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_saucy_pork_1, @tool_board, '切条'),
    (@step_saucy_pork_1, @tool_knife, '切条'),
    (@step_saucy_pork_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_saucy_pork, 2, '煎制',
    '平底锅倒油，将猪里脊煎至表面金黄熟透。',
    6, '中火', JSON_ARRAY('平底锅', '锅铲'),
    '分批煎制避免相互粘连。'
);
SET @step_saucy_pork_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_saucy_pork_2, @tool_flat_pan, '煎制'),
    (@step_saucy_pork_2, @tool_spatula, '翻面');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_saucy_pork, 3, '裹酱',
    '锅中留少许油，下蒜末和豆瓣酱炒香，加入白砂糖、酱油和少量水，倒入猪里脊快速翻匀收汁。',
    3, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '收汁时保持大火使酱汁浓稠包裹肉条。'
);
SET @step_saucy_pork_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_saucy_pork_3, @tool_wok, '裹酱'),
    (@step_saucy_pork_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_saucy_pork, @ing_pork_loin, '300', 'g', '切条腌制', 6, 1, NULL, 429.00, 'main'),
    (@recipe_saucy_pork, @ing_douban, '20', 'g', '调酱', 1, 0, NULL, 37.00, 'seasoning'),
    (@recipe_saucy_pork, @ing_garlic, '10', 'g', '切末', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_saucy_pork, @ing_soy_sauce, '18', 'ml', '调味', 0, 0, NULL, 12.96, 'seasoning'),
    (@recipe_saucy_pork, @ing_shaoxing_wine, '10', 'ml', '腌制', 0, 0, NULL, 5.20, 'seasoning'),
    (@recipe_saucy_pork, @ing_sugar, '8', 'g', '调味', 0, 0, NULL, 30.96, 'seasoning'),
    (@recipe_saucy_pork, @ing_cornstarch, '14', 'g', '腌制', 1, 0, NULL, 53.34, 'seasoning'),
    (@recipe_saucy_pork, @ing_cooking_oil, '22', 'g', '煎炒', 0, 0, NULL, 194.48, 'seasoning'),
    (@recipe_saucy_pork, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 29: 木耳炒鸡蛋
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '木耳炒鸡蛋',
    '木耳搭配鸡蛋滑炒，口感Q弹清爽。',
    'https://images.example.com/muer_chaojidan.jpg',
    'https://videos.example.com/muer_chaojidan.mp4',
    15, 2, 'easy', @cuisine_home,
    320.00, 20.00, 14.00, 22.00
);
SET @recipe_wood_ear_egg := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_wood_ear_egg, 1, '准备',
    '鸡蛋打散加少许盐，木耳泡发后切丝，青椒切丝，蒜切片。',
    4, '常温', JSON_ARRAY('搅拌碗', '砧板', '菜刀'),
    '木耳泡发后挤干水分，炒制更脆。'
);
SET @step_wood_ear_egg_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_wood_ear_egg_1, @tool_mix_bowl, '打蛋'),
    (@step_wood_ear_egg_1, @tool_board, '切丝'),
    (@step_wood_ear_egg_1, @tool_knife, '切丝');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_wood_ear_egg, 2, '炒蛋',
    '热锅倒油，倒入蛋液快速翻炒成蓬松蛋块盛出。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '炒蛋至七成熟即可盛出保持嫩度。'
);
SET @step_wood_ear_egg_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_wood_ear_egg_2, @tool_wok, '炒蛋'),
    (@step_wood_ear_egg_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_wood_ear_egg, 3, '合炒',
    '锅内留少许油，下蒜片、木耳和青椒炒香，再倒入鸡蛋，调入酱油和盐快速翻匀。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '最后淋少许香油提香即可。'
);
SET @step_wood_ear_egg_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_wood_ear_egg_3, @tool_wok, '翻炒'),
    (@step_wood_ear_egg_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_wood_ear_egg, @ing_egg, '4', '个', '打散', 2, 1, NULL, 572.00, 'main'),
    (@recipe_wood_ear_egg, @ing_wood_ear, '60', 'g', '泡发切丝', 8, 0, NULL, 15.00, 'auxiliary'),
    (@recipe_wood_ear_egg, @ing_green_pepper, '80', 'g', '切丝', 2, 0, NULL, 16.00, 'auxiliary'),
    (@recipe_wood_ear_egg, @ing_garlic, '10', 'g', '切片', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_wood_ear_egg, @ing_soy_sauce, '10', 'ml', '调味', 0, 0, NULL, 7.20, 'seasoning'),
    (@recipe_wood_ear_egg, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_wood_ear_egg, @ing_sesame_oil, '5', 'ml', '提香', 0, 0, NULL, 44.20, 'seasoning'),
    (@recipe_wood_ear_egg, @ing_cooking_oil, '14', 'g', '炒制', 0, 0, NULL, 123.76, 'seasoning');

-- Recipe 30: 青椒土豆牛肉丝
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '青椒土豆牛肉丝',
    '土豆丝与牛肉丝搭配青椒快炒，香辣爽口。',
    'https://images.example.com/qingjiao_tudou_niurousi.jpg',
    'https://videos.example.com/qingjiao_tudou_niurousi.mp4',
    20, 2, 'medium', @cuisine_sichuan,
    520.00, 34.00, 32.00, 24.00
);
SET @recipe_potato_beef := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_potato_beef, 1, '切配',
    '牛里脊切丝加酱油、淀粉腌制；土豆切细丝泡水去淀粉，青椒切丝，蒜姜切末。',
    6, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '土豆丝泡水保持脆爽，炒前充分沥干。'
);
SET @step_potato_beef_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_potato_beef_1, @tool_board, '切丝'),
    (@step_potato_beef_1, @tool_knife, '切丝'),
    (@step_potato_beef_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_potato_beef, 2, '滑炒',
    '热锅倒油，下牛肉丝快速滑散至变色盛出。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '滑炒牛肉时油温要高，动作迅速。'
);
SET @step_potato_beef_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_potato_beef_2, @tool_wok, '滑炒'),
    (@step_potato_beef_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_potato_beef, 3, '合炒',
    '锅内留少油，下蒜姜末和豆瓣酱炒香，加入土豆丝和青椒丝翻炒2分钟，再倒入牛肉丝、酱油和盐快速翻匀出锅。',
    3, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '全程大火保持土豆爽脆口感。'
);
SET @step_potato_beef_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_potato_beef_3, @tool_wok, '翻炒'),
    (@step_potato_beef_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_potato_beef, @ing_beef_tenderloin, '280', 'g', '切丝腌制', 5, 1, NULL, 501.60, 'main'),
    (@recipe_potato_beef, @ing_potato, '260', 'g', '切丝', 4, 0, NULL, 200.20, 'auxiliary'),
    (@recipe_potato_beef, @ing_green_pepper, '90', 'g', '切丝', 2, 0, NULL, 18.00, 'auxiliary'),
    (@recipe_potato_beef, @ing_garlic, '10', 'g', '切末', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_potato_beef, @ing_ginger, '8', 'g', '切末', 1, 0, NULL, 6.40, 'seasoning'),
    (@recipe_potato_beef, @ing_douban, '12', 'g', '炒香', 1, 0, NULL, 22.20, 'seasoning'),
    (@recipe_potato_beef, @ing_soy_sauce, '12', 'ml', '调味', 0, 0, NULL, 8.64, 'seasoning'),
    (@recipe_potato_beef, @ing_cornstarch, '10', 'g', '腌制', 1, 0, NULL, 38.10, 'seasoning'),
    (@recipe_potato_beef, @ing_cooking_oil, '18', 'g', '炒制', 0, 0, NULL, 159.12, 'seasoning'),
    (@recipe_potato_beef, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 31: 香菇滑鸡丁
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '香菇滑鸡丁',
    '香菇与鸡丁同炒，滑嫩入味，蒜姜香气浓郁。',
    'https://images.example.com/xianggu_huajiding.jpg',
    'https://videos.example.com/xianggu_huajiding.mp4',
    24, 2, 'medium', @cuisine_home,
    480.00, 46.00, 20.00, 24.00
);
SET @recipe_mushroom_chicken := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_mushroom_chicken, 1, '腌制',
    '鸡胸肉切丁加入酱油、玉米淀粉与香油抓匀，香菇切片，蒜姜切末备用。',
    6, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '鸡丁抓匀后静置 5 分钟可更入味。'
);
SET @step_mushroom_chicken_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_mushroom_chicken_1, @tool_board, '切配'),
    (@step_mushroom_chicken_1, @tool_knife, '切配'),
    (@step_mushroom_chicken_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_mushroom_chicken, 2, '滑炒',
    '热锅倒入 12g 食用油，下鸡丁快速滑散至表面泛白盛出。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '滑炒时持续翻动避免结块。'
);
SET @step_mushroom_chicken_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_mushroom_chicken_2, @tool_wok, '滑炒'),
    (@step_mushroom_chicken_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_mushroom_chicken, 3, '合炒',
    '锅内留油，下蒜姜末与香菇翻炒 2 分钟，倒回鸡丁，调入剩余酱油与盐，翻匀出锅。',
    4, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '出锅前可滴 2ml 香油提香。'
);
SET @step_mushroom_chicken_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_mushroom_chicken_3, @tool_wok, '翻炒'),
    (@step_mushroom_chicken_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_mushroom_chicken, @ing_chicken, '320', 'g', '切丁腌制', 6, 1, NULL, 512.00, 'main'),
    (@recipe_mushroom_chicken, @ing_shiitake, '120', 'g', '切片', 2, 0, NULL, 40.80, 'auxiliary'),
    (@recipe_mushroom_chicken, @ing_garlic, '12', 'g', '切末', 2, 0, NULL, 17.88, 'seasoning'),
    (@recipe_mushroom_chicken, @ing_ginger, '10', 'g', '切末', 1, 0, NULL, 8.00, 'seasoning'),
    (@recipe_mushroom_chicken, @ing_soy_sauce, '18', 'ml', '调味', 0, 0, NULL, 12.96, 'seasoning'),
    (@recipe_mushroom_chicken, @ing_cornstarch, '12', 'g', '腌制', 1, 0, NULL, 45.72, 'seasoning'),
    (@recipe_mushroom_chicken, @ing_sesame_oil, '6', 'ml', '腌制', 0, 0, NULL, 53.04, 'seasoning'),
    (@recipe_mushroom_chicken, @ing_cooking_oil, '18', 'g', '滑炒', 0, 0, NULL, 159.12, 'seasoning'),
    (@recipe_mushroom_chicken, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 32: 青椒胡萝卜炒牛肉
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '青椒胡萝卜炒牛肉',
    '青椒与胡萝卜搭配牛肉丝，色彩鲜艳，口感爽脆。',
    'https://images.example.com/qingjiao_huluobo_niurou.jpg',
    'https://videos.example.com/qingjiao_huluobo_niurou.mp4',
    23, 2, 'medium', @cuisine_home,
    540.00, 44.00, 18.00, 28.00
);
SET @recipe_beef_pepper_carrot := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_beef_pepper_carrot, 1, '腌制',
    '牛里脊切细丝加入酱油、黑胡椒与玉米淀粉腌制 8 分钟，青椒与胡萝卜切丝，蒜姜切末。',
    8, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '腌制时可加入 3ml 香油锁汁提香。'
);
SET @step_beef_pepper_carrot_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_beef_pepper_carrot_1, @tool_board, '切丝'),
    (@step_beef_pepper_carrot_1, @tool_knife, '切丝'),
    (@step_beef_pepper_carrot_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_beef_pepper_carrot, 2, '滑炒',
    '热锅倒入 16g 食用油，将牛肉丝滑散 1.5 分钟盛出。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '牛肉丝摊平滑炒可避免受热不均。'
);
SET @step_beef_pepper_carrot_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_beef_pepper_carrot_2, @tool_wok, '滑炒'),
    (@step_beef_pepper_carrot_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_beef_pepper_carrot, 3, '合炒',
    '锅内留底油，下蒜姜末、青椒丝与胡萝卜丝翻炒 2 分钟，倒入牛肉丝，调入酱油、盐和 4ml 米醋，快速翻匀。',
    4, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '出锅前撒少许黑胡椒增香。'
);
SET @step_beef_pepper_carrot_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_beef_pepper_carrot_3, @tool_wok, '翻炒'),
    (@step_beef_pepper_carrot_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_beef_pepper_carrot, @ing_beef_tenderloin, '320', 'g', '切丝腌制', 8, 1, NULL, 573.00, 'main'),
    (@recipe_beef_pepper_carrot, @ing_green_pepper, '110', 'g', '切丝', 2, 0, NULL, 22.00, 'auxiliary'),
    (@recipe_beef_pepper_carrot, @ing_carrot, '80', 'g', '切丝', 2, 0, NULL, 32.80, 'auxiliary'),
    (@recipe_beef_pepper_carrot, @ing_garlic, '12', 'g', '切末', 1, 0, NULL, 17.88, 'seasoning'),
    (@recipe_beef_pepper_carrot, @ing_ginger, '8', 'g', '切末', 1, 0, NULL, 6.40, 'seasoning'),
    (@recipe_beef_pepper_carrot, @ing_soy_sauce, '18', 'ml', '调味', 0, 0, NULL, 12.96, 'seasoning'),
    (@recipe_beef_pepper_carrot, @ing_black_pepper, '4', 'g', '碾碎', 0, 0, NULL, 10.20, 'seasoning'),
    (@recipe_beef_pepper_carrot, @ing_vinegar, '4', 'ml', '增香', 0, 0, NULL, 0.72, 'seasoning'),
    (@recipe_beef_pepper_carrot, @ing_cornstarch, '10', 'g', '腌制', 1, 0, NULL, 38.10, 'seasoning'),
    (@recipe_beef_pepper_carrot, @ing_sesame_oil, '3', 'ml', '腌制', 0, 0, NULL, 26.52, 'seasoning'),
    (@recipe_beef_pepper_carrot, @ing_cooking_oil, '18', 'g', '炒制', 0, 0, NULL, 159.12, 'seasoning'),
    (@recipe_beef_pepper_carrot, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 33: 蒜香玉米青豆
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '蒜香玉米青豆',
    '玉米粒与青豆搭配蒜蓉快炒，口感清甜，营养均衡。',
    'https://images.example.com/suanxiang_yumi_qingdou.jpg',
    'https://videos.example.com/suanxiang_yumi_qingdou.mp4',
    15, 2, 'easy', @cuisine_home,
    260.00, 10.00, 40.00, 6.00
);
SET @recipe_corn_pea_garlic := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_corn_pea_garlic, 1, '焯烫',
    '玉米粒与青豆入沸水焯 60 秒，捞出沥干备用。',
    2, '大火', JSON_ARRAY('汤锅'),
    '焯烫能去腥并保持颗粒饱满。'
);
SET @step_corn_pea_garlic_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_corn_pea_garlic_1, @tool_soup_pot, '焯烫');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_corn_pea_garlic, 2, '爆香',
    '热锅加入 10g 食用油，下蒜末小火炒香 30 秒。',
    1, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '蒜末微微金黄即可，避免焦糊。'
);
SET @step_corn_pea_garlic_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_corn_pea_garlic_2, @tool_wok, '爆香'),
    (@step_corn_pea_garlic_2, @tool_spatula, '翻动');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_corn_pea_garlic, 3, '快炒',
    '倒入玉米粒与青豆，调入盐、白砂糖，翻炒 2 分钟，淋入 4ml 香油即可出锅。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '出锅前可加 10ml 清水帮助佐料均匀裹附。'
);
SET @step_corn_pea_garlic_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_corn_pea_garlic_3, @tool_wok, '翻炒'),
    (@step_corn_pea_garlic_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_corn_pea_garlic, @ing_corn_kernel, '180', 'g', '焯烫', 2, 1, NULL, 154.80, 'main'),
    (@recipe_corn_pea_garlic, @ing_green_pea, '140', 'g', '焯烫', 2, 0, NULL, 165.20, 'auxiliary'),
    (@recipe_corn_pea_garlic, @ing_garlic, '14', 'g', '切末', 1, 0, NULL, 20.86, 'seasoning'),
    (@recipe_corn_pea_garlic, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_corn_pea_garlic, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_corn_pea_garlic, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_corn_pea_garlic, @ing_cooking_oil, '12', 'g', '翻炒', 0, 0, NULL, 106.08, 'seasoning');

-- Recipe 34: 番茄豆腐汤
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '番茄豆腐汤',
    '番茄酸甜与嫩豆腐结合，汤汁清爽，适合餐前暖胃。',
    'https://images.example.com/fanqie_doufutang.jpg',
    'https://videos.example.com/fanqie_doufutang.mp4',
    18, 3, 'easy', @cuisine_home,
    220.00, 14.00, 18.00, 8.00
);
SET @recipe_tomato_tofu_soup := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_tomato_tofu_soup, 1, '切配',
    '番茄切块，嫩豆腐切片，小葱切段，姜切丝备用。',
    3, '常温', JSON_ARRAY('砧板', '菜刀'),
    '番茄切块后可轻压出汁，汤更浓郁。'
);
SET @step_tomato_tofu_soup_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_tomato_tofu_soup_1, @tool_board, '切配'),
    (@step_tomato_tofu_soup_1, @tool_knife, '切配');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_tomato_tofu_soup, 2, '煸香',
    '汤锅加入 6g 食用油，下姜丝与番茄炒软至出汁。',
    2, '中火', JSON_ARRAY('汤锅'),
    '番茄炒软后再加水味道更浓。'
);
SET @step_tomato_tofu_soup_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_tomato_tofu_soup_2, @tool_soup_pot, '煸香');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_tomato_tofu_soup, 3, '煮汤',
    '倒入 600ml 清水煮沸，放入豆腐片煮 4 分钟，调入盐、白砂糖与香油，撒上小葱即可。',
    6, '中火', JSON_ARRAY('汤锅'),
    '豆腐入锅后改小火避免碎裂。'
);
SET @step_tomato_tofu_soup_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_tomato_tofu_soup_3, @tool_soup_pot, '煮汤');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_tomato_tofu_soup, @ing_tomato, '320', 'g', '切块', 3, 1, NULL, 57.60, 'main'),
    (@recipe_tomato_tofu_soup, @ing_soft_tofu, '360', 'g', '切片', 2, 0, NULL, 252.00, 'auxiliary'),
    (@recipe_tomato_tofu_soup, @ing_ginger, '6', 'g', '切丝', 1, 0, NULL, 4.80, 'seasoning'),
    (@recipe_tomato_tofu_soup, @ing_scallion, '12', 'g', '切段', 1, 0, NULL, 3.84, 'seasoning'),
    (@recipe_tomato_tofu_soup, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_tomato_tofu_soup, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_tomato_tofu_soup, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_tomato_tofu_soup, @ing_cooking_oil, '6', 'g', '煸香', 0, 0, NULL, 53.04, 'seasoning');

-- Recipe 35: 酱爆虾仁
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '酱爆虾仁',
    '虾仁裹酱爆炒，口感鲜辣，适合配饭或面条。',
    'https://images.example.com/jiangbao_xiaren.jpg',
    'https://videos.example.com/jiangbao_xiaren.mp4',
    16, 2, 'easy', @cuisine_sichuan,
    360.00, 32.00, 16.00, 18.00
);
SET @recipe_saucy_shrimp := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_saucy_shrimp, 1, '腌制',
    '虾仁开背去虾线，加入盐、玉米淀粉与绍兴酒抓匀腌 5 分钟。',
    5, '常温', JSON_ARRAY('搅拌碗'),
    '腌制时轻轻按摩虾仁让调味均匀渗透。'
);
SET @step_saucy_shrimp_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_saucy_shrimp_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_saucy_shrimp, 2, '滑炒',
    '热锅倒油，下虾仁滑炒 1 分钟至变色盛出。',
    1, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '虾仁刚蜷曲即可盛出避免过老。'
);
SET @step_saucy_shrimp_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_saucy_shrimp_2, @tool_wok, '滑炒'),
    (@step_saucy_shrimp_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_saucy_shrimp, 3, '爆酱',
    '锅内留油，下蒜姜末与豆瓣酱炒香，倒入虾仁、酱油、白砂糖与米醋，大火翻炒 2 分钟收汁。',
    3, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '酱汁浓稠包裹虾仁即可关火。'
);
SET @step_saucy_shrimp_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_saucy_shrimp_3, @tool_wok, '翻炒'),
    (@step_saucy_shrimp_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_saucy_shrimp, @ing_shrimp, '240', 'g', '腌制', 5, 1, NULL, 228.00, 'main'),
    (@recipe_saucy_shrimp, @ing_douban, '18', 'g', '炒香', 1, 0, NULL, 33.30, 'seasoning'),
    (@recipe_saucy_shrimp, @ing_garlic, '10', 'g', '切末', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_saucy_shrimp, @ing_ginger, '8', 'g', '切末', 1, 0, NULL, 6.40, 'seasoning'),
    (@recipe_saucy_shrimp, @ing_soy_sauce, '12', 'ml', '调味', 0, 0, NULL, 8.64, 'seasoning'),
    (@recipe_saucy_shrimp, @ing_sugar, '6', 'g', '调味', 0, 0, NULL, 23.22, 'seasoning'),
    (@recipe_saucy_shrimp, @ing_vinegar, '6', 'ml', '调味', 0, 0, NULL, 1.08, 'seasoning'),
    (@recipe_saucy_shrimp, @ing_shaoxing_wine, '10', 'ml', '腌制', 0, 0, NULL, 5.20, 'seasoning'),
    (@recipe_saucy_shrimp, @ing_cornstarch, '10', 'g', '腌制', 1, 0, NULL, 38.10, 'seasoning'),
    (@recipe_saucy_shrimp, @ing_cooking_oil, '18', 'g', '炒制', 0, 0, NULL, 159.12, 'seasoning'),
    (@recipe_saucy_shrimp, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 36: 柠檬香煎鸡胸
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '柠檬香煎鸡胸',
    '鸡胸肉搭配柠檬煎制，口感清爽，外表金黄。',
    'https://images.example.com/ningmeng_xiangjian_jixiong.jpg',
    'https://videos.example.com/ningmeng_xiangjian_jixiong.mp4',
    18, 2, 'easy', @cuisine_home,
    410.00, 38.00, 12.00, 20.00
);
SET @recipe_lemon_pan_chicken := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_lemon_pan_chicken, 1, '腌制',
    '鸡胸肉拍松后抹上盐、黑胡椒和 10ml 柠檬汁，再淋入 4ml 香油腌 6 分钟。',
    6, '常温', JSON_ARRAY('砧板', '菜刀', '腌制碗'),
    '腌制时翻面 2 次保证受味均匀。'
);
SET @step_lemon_pan_chicken_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_lemon_pan_chicken_1, @tool_board, '处理'),
    (@step_lemon_pan_chicken_1, @tool_knife, '处理'),
    (@step_lemon_pan_chicken_1, @tool_marinade_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_lemon_pan_chicken, 2, '煎制',
    '平底锅加 14g 食用油，中火煎鸡胸 3 分钟后翻面再煎 3 分钟至熟。',
    6, '中火', JSON_ARRAY('平底锅', '锅铲'),
    '煎制过程中适度压实可获得更均匀焦化。'
);
SET @step_lemon_pan_chicken_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_lemon_pan_chicken_2, @tool_flat_pan, '煎制'),
    (@step_lemon_pan_chicken_2, @tool_spatula, '翻面');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_lemon_pan_chicken, 3, '调味',
    '关火后撒入蒜末和剩余柠檬汁，静置 1 分钟使味道渗透。',
    1, '常温', JSON_ARRAY('平底锅'),
    '静置阶段让肉质回汁更加多汁。'
);
SET @step_lemon_pan_chicken_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_lemon_pan_chicken_3, @tool_flat_pan, '调味');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_lemon_pan_chicken, @ing_chicken, '320', 'g', '腌制', 6, 1, NULL, 512.00, 'main'),
    (@recipe_lemon_pan_chicken, @ing_lemon, '1', '个', '榨汁', 2, 0, NULL, 29.00, 'auxiliary'),
    (@recipe_lemon_pan_chicken, @ing_garlic, '8', 'g', '切末', 1, 0, NULL, 11.92, 'seasoning'),
    (@recipe_lemon_pan_chicken, @ing_black_pepper, '4', 'g', '碾碎', 0, 0, NULL, 10.20, 'seasoning'),
    (@recipe_lemon_pan_chicken, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_lemon_pan_chicken, @ing_sesame_oil, '4', 'ml', '腌制', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_lemon_pan_chicken, @ing_cooking_oil, '14', 'g', '煎制', 0, 0, NULL, 123.76, 'seasoning');

-- Recipe 37: 姜汁蒸鸡腿
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '姜汁蒸鸡腿',
    '鸡腿肉搭配姜汁蒸制，肉质软嫩，汤汁清亮。',
    'https://images.example.com/jiangzhi_zheng_jitui.jpg',
    'https://videos.example.com/jiangzhi_zheng_jitui.mp4',
    28, 2, 'easy', @cuisine_cantonese,
    380.00, 36.00, 10.00, 18.00
);
SET @recipe_ginger_steam_chicken := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_ginger_steam_chicken, 1, '腌制',
    '鸡腿肉切块放入碗中，加入姜丝、酱油、绍兴酒与盐抓匀腌 12 分钟。',
    12, '常温', JSON_ARRAY('腌制碗', '砧板', '菜刀'),
    '腌制时以姜汁覆盖鸡肉表面能有效去腥。'
);
SET @step_ginger_steam_chicken_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_ginger_steam_chicken_1, @tool_board, '切块'),
    (@step_ginger_steam_chicken_1, @tool_knife, '切块'),
    (@step_ginger_steam_chicken_1, @tool_marinade_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_ginger_steam_chicken, 2, '蒸制',
    '蒸锅水开后置入鸡腿肉，蒸 12 分钟至熟。',
    12, '大火', JSON_ARRAY('蒸锅'),
    '中途可打开一次检查水位避免烧干。'
);
SET @step_ginger_steam_chicken_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_ginger_steam_chicken_2, @tool_steamer, '蒸制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_ginger_steam_chicken, 3, '调味',
    '出锅后撒入蒜末，淋上 4ml 香油与 6ml 蒸鱼豉油，轻拌均匀即可。',
    1, '常温', JSON_ARRAY('腌制碗'),
    '趁热拌入调味料能更好吸附。'
);
SET @step_ginger_steam_chicken_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_ginger_steam_chicken_3, @tool_marinade_bowl, '调味');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_ginger_steam_chicken, @ing_chicken_leg, '420', 'g', '切块腌制', 12, 1, NULL, 744.00, 'main'),
    (@recipe_ginger_steam_chicken, @ing_ginger, '18', 'g', '切丝', 2, 0, NULL, 14.40, 'seasoning'),
    (@recipe_ginger_steam_chicken, @ing_garlic, '10', 'g', '切末', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_ginger_steam_chicken, @ing_soy_sauce, '16', 'ml', '腌制', 0, 0, NULL, 11.52, 'seasoning'),
    (@recipe_ginger_steam_chicken, @ing_shaoxing_wine, '12', 'ml', '腌制', 0, 0, NULL, 6.24, 'seasoning'),
    (@recipe_ginger_steam_chicken, @ing_steaming_sauce, '6', 'ml', '调味', 0, 0, NULL, 4.32, 'seasoning'),
    (@recipe_ginger_steam_chicken, @ing_sesame_oil, '4', 'ml', '调味', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_ginger_steam_chicken, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 38: 豆豉蒸鲈鱼
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '豆豉蒸鲈鱼',
    '豆豉与蒜蓉搭配蒸鲈鱼，鲜美微辣，汁水丰盈。',
    'https://images.example.com/douchi_zheng_luyu.jpg',
    'https://videos.example.com/douchi_zheng_luyu.mp4',
    24, 2, 'easy', @cuisine_cantonese,
    340.00, 48.00, 8.00, 12.00
);
SET @recipe_blackbean_steam_bass := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_blackbean_steam_bass, 1, '准备',
    '鲈鱼划花刀，抹上盐与料酒，豆豉与蒜末拌匀成酱。',
    6, '常温', JSON_ARRAY('砧板', '菜刀', '腌制碗'),
    '在鱼身抹少许柠檬汁可进一步去腥。'
);
SET @step_blackbean_steam_bass_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_blackbean_steam_bass_1, @tool_board, '改刀'),
    (@step_blackbean_steam_bass_1, @tool_knife, '改刀'),
    (@step_blackbean_steam_bass_1, @tool_marinade_bowl, '调酱');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_blackbean_steam_bass, 2, '蒸制',
    '将豆豉蒜蓉铺满鱼身，放入蒸锅，大火蒸 10 分钟。',
    10, '大火', JSON_ARRAY('蒸锅'),
    '蒸制结束后焖 1 分钟让味道渗透。'
);
SET @step_blackbean_steam_bass_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_blackbean_steam_bass_2, @tool_steamer, '蒸制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_blackbean_steam_bass, 3, '浇油',
    '出锅后淋上 10ml 热油与 6ml 蒸鱼豉油，再撒小葱段。',
    1, '常温', JSON_ARRAY('腌制碗'),
    '热油浇淋使豆豉香味爆发。'
);
SET @step_blackbean_steam_bass_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_blackbean_steam_bass_3, @tool_marinade_bowl, '调味');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_blackbean_steam_bass, @ing_sea_bass, '1', '条', '改刀', 6, 1, NULL, 290.00, 'main'),
    (@recipe_blackbean_steam_bass, @ing_fermented_black_bean, '22', 'g', '剁碎', 1, 0, NULL, 44.00, 'seasoning'),
    (@recipe_blackbean_steam_bass, @ing_garlic, '18', 'g', '切末', 2, 0, NULL, 26.82, 'seasoning'),
    (@recipe_blackbean_steam_bass, @ing_scallion, '10', 'g', '切段', 1, 0, NULL, 3.20, 'seasoning'),
    (@recipe_blackbean_steam_bass, @ing_shaoxing_wine, '12', 'ml', '腌制', 0, 0, NULL, 6.24, 'seasoning'),
    (@recipe_blackbean_steam_bass, @ing_sesame_oil, '4', 'ml', '调味', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_blackbean_steam_bass, @ing_steaming_sauce, '6', 'ml', '调味', 0, 0, NULL, 4.32, 'seasoning'),
    (@recipe_blackbean_steam_bass, @ing_cooking_oil, '12', 'g', '浇油', 0, 0, NULL, 106.08, 'seasoning'),
    (@recipe_blackbean_steam_bass, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 39: 花椒土豆片
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '花椒土豆片',
    '土豆片与花椒、干辣椒同炒，麻辣开胃，口感爽脆。',
    'https://images.example.com/huajiao_tudoupian.jpg',
    'https://videos.example.com/huajiao_tudoupian.mp4',
    17, 2, 'easy', @cuisine_sichuan,
    300.00, 8.00, 44.00, 10.00
);
SET @recipe_sichuan_potato := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_sichuan_potato, 1, '切片',
    '土豆去皮切薄片，浸泡清水 5 分钟去除多余淀粉。',
    5, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '浸泡后充分沥干可防止炒制粘锅。'
);
SET @step_sichuan_potato_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_sichuan_potato_1, @tool_board, '切片'),
    (@step_sichuan_potato_1, @tool_knife, '切片'),
    (@step_sichuan_potato_1, @tool_mix_bowl, '浸泡');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_sichuan_potato, 2, '炝锅',
    '热锅倒油，下花椒与干辣椒小火炝香 30 秒。',
    1, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '炝香时持续翻动避免糊锅。'
);
SET @step_sichuan_potato_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_sichuan_potato_2, @tool_wok, '炝锅'),
    (@step_sichuan_potato_2, @tool_spatula, '翻动');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_sichuan_potato, 3, '快炒',
    '倒入土豆片与蒜片大火翻炒 3 分钟，调入盐、酱油与米醋，继续翻炒 1 分钟即可。',
    4, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '最后淋入 10ml 清水帮助调味均匀。'
);
SET @step_sichuan_potato_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_sichuan_potato_3, @tool_wok, '翻炒'),
    (@step_sichuan_potato_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_sichuan_potato, @ing_potato, '360', 'g', '切片浸泡', 5, 1, NULL, 277.20, 'main'),
    (@recipe_sichuan_potato, @ing_sichuan_pepper, '4', 'g', '炝香', 0, 0, NULL, 12.00, 'seasoning'),
    (@recipe_sichuan_potato, @ing_dried_chili, '8', 'g', '剪段', 1, 0, NULL, 12.00, 'seasoning'),
    (@recipe_sichuan_potato, @ing_garlic, '10', 'g', '切片', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_sichuan_potato, @ing_soy_sauce, '10', 'ml', '调味', 0, 0, NULL, 7.20, 'seasoning'),
    (@recipe_sichuan_potato, @ing_vinegar, '8', 'ml', '调味', 0, 0, NULL, 1.44, 'seasoning'),
    (@recipe_sichuan_potato, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_sichuan_potato, @ing_cooking_oil, '14', 'g', '煸炒', 0, 0, NULL, 123.76, 'seasoning');

-- Recipe 40: 蒜蓉蒸西兰花
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '蒜蓉蒸西兰花',
    '蒸制西兰花保持脆度，蒜蓉汁浇淋更加鲜香。',
    'https://images.example.com/suanrong_zheng_xilanhua.jpg',
    'https://videos.example.com/suanrong_zheng_xilanhua.mp4',
    14, 2, 'easy', @cuisine_home,
    210.00, 12.00, 24.00, 8.00
);
SET @recipe_steamed_broccoli_garlic := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_steamed_broccoli_garlic, 1, '焯烫',
    '西兰花掰成小朵焯水 50 秒后过凉，沥干摆盘。',
    2, '大火', JSON_ARRAY('汤锅'),
    '焯烫后迅速过冰水保持翠绿。'
);
SET @step_steamed_broccoli_garlic_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_steamed_broccoli_garlic_1, @tool_soup_pot, '焯烫');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_steamed_broccoli_garlic, 2, '蒸制',
    '将西兰花入蒸锅，大火蒸 4 分钟。',
    4, '大火', JSON_ARRAY('蒸锅'),
    '蒸制时间不宜过长以免变软。'
);
SET @step_steamed_broccoli_garlic_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_steamed_broccoli_garlic_2, @tool_steamer, '蒸制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_steamed_broccoli_garlic, 3, '调汁',
    '锅中加 8g 食用油，下蒜末炒香，调入酱油、盐与香油，淋在蒸好的西兰花上。',
    2, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '蒜末呈浅金色即可关火，避免发苦。'
);
SET @step_steamed_broccoli_garlic_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_steamed_broccoli_garlic_3, @tool_wok, '调汁'),
    (@step_steamed_broccoli_garlic_3, @tool_spatula, '搅拌');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_steamed_broccoli_garlic, @ing_broccoli, '360', 'g', '焯烫', 3, 1, NULL, 122.40, 'main'),
    (@recipe_steamed_broccoli_garlic, @ing_garlic, '16', 'g', '切末', 2, 0, NULL, 23.84, 'seasoning'),
    (@recipe_steamed_broccoli_garlic, @ing_soy_sauce, '12', 'ml', '调味', 0, 0, NULL, 8.64, 'seasoning'),
    (@recipe_steamed_broccoli_garlic, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_steamed_broccoli_garlic, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_steamed_broccoli_garlic, @ing_cooking_oil, '8', 'g', '炒汁', 0, 0, NULL, 70.88, 'seasoning');

-- Recipe 41: 双椒牛肉丝
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '双椒牛肉丝',
    '青椒与干椒双重激发牛肉香气，麻辣爽口。',
    'https://images.example.com/shuangjiao_niurousi.jpg',
    'https://videos.example.com/shuangjiao_niurousi.mp4',
    22, 2, 'medium', @cuisine_sichuan,
    520.00, 42.00, 20.00, 26.00
);
SET @recipe_double_pepper_beef := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_double_pepper_beef, 1, '腌制',
    '牛里脊切丝加入酱油、玉米淀粉、黑胡椒和香油抓匀，青椒切条，干辣椒剪段。',
    7, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '腌制时加入 5ml 清水帮助肉丝更嫩。'
);
SET @step_double_pepper_beef_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_double_pepper_beef_1, @tool_board, '切丝'),
    (@step_double_pepper_beef_1, @tool_knife, '切丝'),
    (@step_double_pepper_beef_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_double_pepper_beef, 2, '滑炒',
    '热锅到冒烟后倒入 18g 油，将牛肉丝滑散 1.5 分钟盛出。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '分批滑炒可保持锅内温度充足。'
);
SET @step_double_pepper_beef_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_double_pepper_beef_2, @tool_wok, '滑炒'),
    (@step_double_pepper_beef_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_double_pepper_beef, 3, '合炒',
    '锅内留少油，下蒜末、干辣椒与花椒炒香，倒入青椒条与牛肉丝，调入酱油、米醋和盐翻炒 2 分钟。',
    3, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '最后滴入 3ml 香油即可出锅。'
);
SET @step_double_pepper_beef_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_double_pepper_beef_3, @tool_wok, '翻炒'),
    (@step_double_pepper_beef_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_double_pepper_beef, @ing_beef_tenderloin, '300', 'g', '切丝腌制', 7, 1, NULL, 537.00, 'main'),
    (@recipe_double_pepper_beef, @ing_green_pepper, '140', 'g', '切条', 2, 0, NULL, 28.00, 'auxiliary'),
    (@recipe_double_pepper_beef, @ing_dried_chili, '12', 'g', '剪段', 1, 0, NULL, 18.00, 'seasoning'),
    (@recipe_double_pepper_beef, @ing_sichuan_pepper, '3', 'g', '爆香', 0, 0, NULL, 9.00, 'seasoning'),
    (@recipe_double_pepper_beef, @ing_garlic, '10', 'g', '切末', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_double_pepper_beef, @ing_soy_sauce, '16', 'ml', '调味', 0, 0, NULL, 11.52, 'seasoning'),
    (@recipe_double_pepper_beef, @ing_vinegar, '6', 'ml', '提味', 0, 0, NULL, 1.08, 'seasoning'),
    (@recipe_double_pepper_beef, @ing_black_pepper, '3', 'g', '腌制', 0, 0, NULL, 7.65, 'seasoning'),
    (@recipe_double_pepper_beef, @ing_cornstarch, '10', 'g', '腌制', 1, 0, NULL, 38.10, 'seasoning'),
    (@recipe_double_pepper_beef, @ing_sesame_oil, '3', 'ml', '腌制/提香', 0, 0, NULL, 26.52, 'seasoning'),
    (@recipe_double_pepper_beef, @ing_cooking_oil, '20', 'g', '炒制', 0, 0, NULL, 176.80, 'seasoning'),
    (@recipe_double_pepper_beef, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 42: 清炒小白菜
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '清炒小白菜',
    '简单快炒的小白菜，保留清脆口感与淡淡蒜香。',
    'https://images.example.com/qingchao_xiaobaicai.jpg',
    'https://videos.example.com/qingchao_xiaobaicai.mp4',
    10, 2, 'easy', @cuisine_home,
    150.00, 8.00, 12.00, 6.00
);
SET @recipe_stirfried_bokchoy := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_stirfried_bokchoy, 1, '处理',
    '小白菜洗净切段，蒜切片备用。',
    2, '常温', JSON_ARRAY('砧板', '菜刀'),
    '叶梗分离能确保炒制火候一致。'
);
SET @step_stirfried_bokchoy_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_stirfried_bokchoy_1, @tool_board, '切段'),
    (@step_stirfried_bokchoy_1, @tool_knife, '切段');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_stirfried_bokchoy, 2, '爆香',
    '热锅入 10g 食用油，下蒜片爆香 20 秒。',
    1, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '蒜片一变金立即加入菜梗。'
);
SET @step_stirfried_bokchoy_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_stirfried_bokchoy_2, @tool_wok, '爆香'),
    (@step_stirfried_bokchoy_2, @tool_spatula, '翻动');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_stirfried_bokchoy, 3, '快炒',
    '先下菜梗炒 1 分钟，再加入菜叶、盐与香油大火翻炒 1 分钟即可出锅。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '全程大火保持菜叶脆爽。'
);
SET @step_stirfried_bokchoy_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_stirfried_bokchoy_3, @tool_wok, '翻炒'),
    (@step_stirfried_bokchoy_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_stirfried_bokchoy, @ing_bok_choy, '320', 'g', '切段', 2, 1, NULL, 41.60, 'main'),
    (@recipe_stirfried_bokchoy, @ing_garlic, '12', 'g', '切片', 1, 0, NULL, 17.88, 'seasoning'),
    (@recipe_stirfried_bokchoy, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_stirfried_bokchoy, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_stirfried_bokchoy, @ing_cooking_oil, '10', 'g', '翻炒', 0, 0, NULL, 88.40, 'seasoning');

-- Recipe 43: 糖醋鸡丁
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '糖醋鸡丁',
    '经典糖醋口味鸡丁，外酥里嫩，酸甜开胃。',
    'https://images.example.com/tangcu_jiding.jpg',
    'https://videos.example.com/tangcu_jiding.mp4',
    26, 2, 'medium', @cuisine_home,
    450.00, 38.00, 28.00, 18.00
);
SET @recipe_sweet_sour_chicken := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_sweet_sour_chicken, 1, '腌制裹粉',
    '鸡胸肉切丁加入盐、玉米淀粉和绍兴酒腌 8 分钟，之后沾上一层干淀粉备用。',
    8, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '裹粉前充分沥干腌汁能提升酥脆度。'
);
SET @step_sweet_sour_chicken_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_sweet_sour_chicken_1, @tool_board, '切丁'),
    (@step_sweet_sour_chicken_1, @tool_knife, '切丁'),
    (@step_sweet_sour_chicken_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_sweet_sour_chicken, 2, '煎炸',
    '平底锅倒入 22g 油，中火将鸡丁两面煎至金黄熟透。',
    6, '中火', JSON_ARRAY('平底锅', '锅铲'),
    '可分两次煎炸确保油温稳定。'
);
SET @step_sweet_sour_chicken_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_sweet_sour_chicken_2, @tool_flat_pan, '煎制'),
    (@step_sweet_sour_chicken_2, @tool_spatula, '翻面');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_sweet_sour_chicken, 3, '调酱',
    '锅内留少油，下蒜末、番茄块翻炒 1 分钟，加入糖、米醋、酱油和 40ml 清水煮沸，倒入鸡丁大火翻炒 2 分钟收汁。',
    3, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '收汁至酱汁均匀包裹鸡丁即可。'
);
SET @step_sweet_sour_chicken_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_sweet_sour_chicken_3, @tool_wok, '翻炒'),
    (@step_sweet_sour_chicken_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_sweet_sour_chicken, @ing_chicken, '340', 'g', '切丁腌制', 8, 1, NULL, 544.00, 'main'),
    (@recipe_sweet_sour_chicken, @ing_tomato, '140', 'g', '切块', 2, 0, NULL, 25.20, 'auxiliary'),
    (@recipe_sweet_sour_chicken, @ing_garlic, '12', 'g', '切末', 1, 0, NULL, 17.88, 'seasoning'),
    (@recipe_sweet_sour_chicken, @ing_sugar, '24', 'g', '调味', 0, 0, NULL, 92.88, 'seasoning'),
    (@recipe_sweet_sour_chicken, @ing_vinegar, '20', 'ml', '调味', 0, 0, NULL, 3.60, 'seasoning'),
    (@recipe_sweet_sour_chicken, @ing_soy_sauce, '14', 'ml', '调味', 0, 0, NULL, 10.08, 'seasoning'),
    (@recipe_sweet_sour_chicken, @ing_shaoxing_wine, '10', 'ml', '腌制', 0, 0, NULL, 5.20, 'seasoning'),
    (@recipe_sweet_sour_chicken, @ing_cornstarch, '24', 'g', '腌制/裹粉', 1, 0, NULL, 91.44, 'seasoning'),
    (@recipe_sweet_sour_chicken, @ing_cooking_oil, '24', 'g', '煎炒', 0, 0, NULL, 211.20, 'seasoning'),
    (@recipe_sweet_sour_chicken, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 44: 胡萝卜炒鸡蛋
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '胡萝卜炒鸡蛋',
    '胡萝卜与鸡蛋搭配快炒，营养丰富，色泽鲜亮。',
    'https://images.example.com/huluobo_chaojidan.jpg',
    'https://videos.example.com/huluobo_chaojidan.mp4',
    12, 2, 'easy', @cuisine_home,
    320.00, 20.00, 18.00, 18.00
);
SET @recipe_carrot_egg := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_carrot_egg, 1, '备料',
    '鸡蛋打散加入 2g 盐调味，胡萝卜切细丝，蒜切末。',
    2, '常温', JSON_ARRAY('搅拌碗', '砧板', '菜刀'),
    '胡萝卜丝尽量细，易熟且口感更好。'
);
SET @step_carrot_egg_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_carrot_egg_1, @tool_mix_bowl, '打蛋'),
    (@step_carrot_egg_1, @tool_board, '切丝'),
    (@step_carrot_egg_1, @tool_knife, '切丝');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_carrot_egg, 2, '炒蛋',
    '热锅倒入 12g 油，倒入蛋液快速翻炒至半凝固盛出。',
    1, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '蛋液稍微凝固即可取出保持嫩度。'
);
SET @step_carrot_egg_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_carrot_egg_2, @tool_wok, '炒蛋'),
    (@step_carrot_egg_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_carrot_egg, 3, '合炒',
    '锅内留油，下蒜末与胡萝卜丝翻炒 2 分钟，再倒入鸡蛋，调入盐、白砂糖与香油翻匀即可。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '胡萝卜稍软即可，避免炒至出水。'
);
SET @step_carrot_egg_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_carrot_egg_3, @tool_wok, '翻炒'),
    (@step_carrot_egg_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_carrot_egg, @ing_egg, '4', '个', '打散', 2, 1, NULL, 572.00, 'main'),
    (@recipe_carrot_egg, @ing_carrot, '160', 'g', '切丝', 3, 0, NULL, 65.60, 'auxiliary'),
    (@recipe_carrot_egg, @ing_garlic, '8', 'g', '切末', 1, 0, NULL, 11.92, 'seasoning'),
    (@recipe_carrot_egg, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_carrot_egg, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_carrot_egg, @ing_cooking_oil, '16', 'g', '翻炒', 0, 0, NULL, 141.44, 'seasoning'),
    (@recipe_carrot_egg, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 45: 玉米青豆汤
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '玉米青豆汤',
    '玉米青豆煮成清甜汤品，简单易做，营养丰富。',
    'https://images.example.com/yumi_qingdou_tang.jpg',
    'https://videos.example.com/yumi_qingdou_tang.mp4',
    14, 3, 'easy', @cuisine_home,
    180.00, 12.00, 28.00, 6.00
);
SET @recipe_corn_pea_soup := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_corn_pea_soup, 1, '焯水',
    '玉米粒、青豆与胡萝卜丁入沸水焯 40 秒捞出备用。',
    1, '大火', JSON_ARRAY('汤锅'),
    '焯水去腥并保持色泽。'
);
SET @step_corn_pea_soup_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_corn_pea_soup_1, @tool_soup_pot, '焯水');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_corn_pea_soup, 2, '煮汤',
    '汤锅加入 700ml 清水，放入焯过的玉米、青豆和胡萝卜，小火煮 6 分钟。',
    6, '小火', JSON_ARRAY('汤锅'),
    '小火慢煮能保持蔬菜甜味。'
);
SET @step_corn_pea_soup_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_corn_pea_soup_2, @tool_soup_pot, '煮汤');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_corn_pea_soup, 3, '调味',
    '加入盐、白砂糖和香油调味，装碗后撒上小葱段。',
    1, '小火', JSON_ARRAY('汤锅'),
    '起锅前可加入 20ml 清鸡汤提升口感。'
);
SET @step_corn_pea_soup_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_corn_pea_soup_3, @tool_soup_pot, '调味');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_corn_pea_soup, @ing_corn_kernel, '140', 'g', '焯水', 1, 1, NULL, 120.40, 'main'),
    (@recipe_corn_pea_soup, @ing_green_pea, '120', 'g', '焯水', 1, 0, NULL, 141.60, 'auxiliary'),
    (@recipe_corn_pea_soup, @ing_carrot, '80', 'g', '切丁', 2, 0, NULL, 32.80, 'auxiliary'),
    (@recipe_corn_pea_soup, @ing_scallion, '10', 'g', '切段', 1, 0, NULL, 3.20, 'seasoning'),
    (@recipe_corn_pea_soup, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_corn_pea_soup, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_corn_pea_soup, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning');

-- Recipe 46: 香煎鸡腿排
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '香煎鸡腿排',
    '去骨鸡腿带皮煎制，肉汁丰富，外皮酥香。',
    'https://images.example.com/xiangjian_jituipai.jpg',
    'https://videos.example.com/xiangjian_jituipai.mp4',
    20, 2, 'medium', @cuisine_home,
    460.00, 40.00, 16.00, 24.00
);
SET @recipe_pan_chicken_thigh := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pan_chicken_thigh, 1, '腌制',
    '鸡腿肉去骨拍平，加入酱油、黑胡椒、白砂糖腌 10 分钟。',
    10, '常温', JSON_ARRAY('砧板', '菜刀', '腌制碗'),
    '腌制时可在皮面划浅刀更易入味。'
);
SET @step_pan_chicken_thigh_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pan_chicken_thigh_1, @tool_board, '去骨'),
    (@step_pan_chicken_thigh_1, @tool_knife, '处理'),
    (@step_pan_chicken_thigh_1, @tool_marinade_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pan_chicken_thigh, 2, '煎制',
    '平底锅中火倒入 16g 油，先将鸡皮面朝下煎 4 分钟，再翻面煎 3 分钟至内部熟透。',
    7, '中火', JSON_ARRAY('平底锅', '锅铲'),
    '煎制时用锅铲轻压鸡皮帮助出油。'
);
SET @step_pan_chicken_thigh_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pan_chicken_thigh_2, @tool_flat_pan, '煎制'),
    (@step_pan_chicken_thigh_2, @tool_spatula, '翻面');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pan_chicken_thigh, 3, '调味',
    '关火后撒上蒜末与香油，静置 1 分钟再切片装盘。',
    1, '常温', JSON_ARRAY('平底锅'),
    '静置能让肉汁重新分布保持多汁。'
);
SET @step_pan_chicken_thigh_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pan_chicken_thigh_3, @tool_flat_pan, '调味');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_pan_chicken_thigh, @ing_chicken_leg, '380', 'g', '去骨腌制', 10, 1, NULL, 672.40, 'main'),
    (@recipe_pan_chicken_thigh, @ing_garlic, '8', 'g', '切末', 1, 0, NULL, 11.92, 'seasoning'),
    (@recipe_pan_chicken_thigh, @ing_soy_sauce, '18', 'ml', '腌制', 0, 0, NULL, 12.96, 'seasoning'),
    (@recipe_pan_chicken_thigh, @ing_black_pepper, '4', 'g', '碾碎', 0, 0, NULL, 10.20, 'seasoning'),
    (@recipe_pan_chicken_thigh, @ing_sugar, '6', 'g', '调味', 0, 0, NULL, 23.22, 'seasoning'),
    (@recipe_pan_chicken_thigh, @ing_sesame_oil, '4', 'ml', '调味', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_pan_chicken_thigh, @ing_cooking_oil, '16', 'g', '煎制', 0, 0, NULL, 141.44, 'seasoning'),
    (@recipe_pan_chicken_thigh, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 47: 酱香豆腐煲
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '酱香豆腐煲',
    '豆瓣酱与猪肉片搭配嫩豆腐，口味浓郁，适合配米饭。',
    'https://images.example.com/jiangxiang_doufubao.jpg',
    'https://videos.example.com/jiangxiang_doufubao.mp4',
    24, 2, 'medium', @cuisine_sichuan,
    480.00, 32.00, 22.00, 26.00
);
SET @recipe_saucy_tofu_casserole := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_saucy_tofu_casserole, 1, '备料',
    '嫩豆腐切块，猪里脊切片后用酱油和淀粉腌 6 分钟，蒜姜切末。',
    6, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '豆腐切块后用热水焯 30 秒可提高韧性。'
);
SET @step_saucy_tofu_casserole_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_saucy_tofu_casserole_1, @tool_board, '切块'),
    (@step_saucy_tofu_casserole_1, @tool_knife, '切片'),
    (@step_saucy_tofu_casserole_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_saucy_tofu_casserole, 2, '煸香',
    '热锅倒油，下蒜姜末与豆瓣酱炒出红油，加入猪肉片翻炒至变色。',
    3, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '豆瓣酱炒至出红油再加肉片味道更浓。'
);
SET @step_saucy_tofu_casserole_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_saucy_tofu_casserole_2, @tool_wok, '煸香'),
    (@step_saucy_tofu_casserole_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_saucy_tofu_casserole, 3, '焖煮',
    '加入豆腐块和 100ml 水，小火焖煮 6 分钟，调入盐、白砂糖与香油，翻匀出锅。',
    6, '小火', JSON_ARRAY('炒锅', '锅铲'),
    '焖煮过程中轻推豆腐避免碎裂。'
);
SET @step_saucy_tofu_casserole_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_saucy_tofu_casserole_3, @tool_wok, '焖煮'),
    (@step_saucy_tofu_casserole_3, @tool_spatula, '翻拌');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_saucy_tofu_casserole, @ing_soft_tofu, '420', 'g', '切块焯水', 4, 1, NULL, 294.00, 'main'),
    (@recipe_saucy_tofu_casserole, @ing_pork_loin, '180', 'g', '切片腌制', 6, 0, NULL, 257.40, 'auxiliary'),
    (@recipe_saucy_tofu_casserole, @ing_douban, '22', 'g', '炒香', 1, 0, NULL, 40.70, 'seasoning'),
    (@recipe_saucy_tofu_casserole, @ing_garlic, '12', 'g', '切末', 1, 0, NULL, 17.88, 'seasoning'),
    (@recipe_saucy_tofu_casserole, @ing_ginger, '8', 'g', '切末', 1, 0, NULL, 6.40, 'seasoning'),
    (@recipe_saucy_tofu_casserole, @ing_soy_sauce, '12', 'ml', '腌制', 0, 0, NULL, 8.64, 'seasoning'),
    (@recipe_saucy_tofu_casserole, @ing_sugar, '6', 'g', '调味', 0, 0, NULL, 23.22, 'seasoning'),
    (@recipe_saucy_tofu_casserole, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_saucy_tofu_casserole, @ing_cornstarch, '8', 'g', '腌制', 1, 0, NULL, 30.48, 'seasoning'),
    (@recipe_saucy_tofu_casserole, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_saucy_tofu_casserole, @ing_cooking_oil, '16', 'g', '炒制', 0, 0, NULL, 141.44, 'seasoning');

-- Recipe 48: 番茄虾仁炒蛋
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '番茄虾仁炒蛋',
    '番茄汁包裹虾仁与鸡蛋，酸甜鲜香，营养丰富。',
    'https://images.example.com/fanqie_xiaren_chaodan.jpg',
    'https://videos.example.com/fanqie_xiaren_chaodan.mp4',
    15, 2, 'easy', @cuisine_home,
    420.00, 34.00, 20.00, 18.00
);
SET @recipe_tomato_shrimp_egg := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_tomato_shrimp_egg, 1, '备料',
    '虾仁用盐与淀粉抓匀，鸡蛋打散，番茄切块，蒜切末。',
    4, '常温', JSON_ARRAY('搅拌碗', '砧板', '菜刀'),
    '虾仁腌制 3 分钟可锁住水分。'
);
SET @step_tomato_shrimp_egg_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_tomato_shrimp_egg_1, @tool_mix_bowl, '腌制/打蛋'),
    (@step_tomato_shrimp_egg_1, @tool_board, '切块'),
    (@step_tomato_shrimp_egg_1, @tool_knife, '切块');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_tomato_shrimp_egg, 2, '炒蛋',
    '热锅倒油，下蛋液炒至七成熟盛出。',
    1, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '炒蛋轻轻翻动即可，保持蓬松。'
);
SET @step_tomato_shrimp_egg_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_tomato_shrimp_egg_2, @tool_wok, '炒蛋'),
    (@step_tomato_shrimp_egg_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_tomato_shrimp_egg, 3, '合炒',
    '锅内留油，下蒜末炒香，加入番茄块与虾仁翻炒 2 分钟，倒入鸡蛋，调入盐、白砂糖与香油翻匀。',
    3, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '番茄出汁后再回蛋，口感更融合。'
);
SET @step_tomato_shrimp_egg_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_tomato_shrimp_egg_3, @tool_wok, '翻炒'),
    (@step_tomato_shrimp_egg_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_tomato_shrimp_egg, @ing_shrimp, '200', 'g', '腌制', 3, 1, NULL, 190.00, 'main'),
    (@recipe_tomato_shrimp_egg, @ing_egg, '3', '个', '打散', 2, 0, NULL, 429.00, 'auxiliary'),
    (@recipe_tomato_shrimp_egg, @ing_tomato, '220', 'g', '切块', 2, 0, NULL, 39.60, 'auxiliary'),
    (@recipe_tomato_shrimp_egg, @ing_garlic, '10', 'g', '切末', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_tomato_shrimp_egg, @ing_sugar, '6', 'g', '调味', 0, 0, NULL, 23.22, 'seasoning'),
    (@recipe_tomato_shrimp_egg, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_tomato_shrimp_egg, @ing_cornstarch, '6', 'g', '腌制', 1, 0, NULL, 22.86, 'seasoning'),
    (@recipe_tomato_shrimp_egg, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_tomato_shrimp_egg, @ing_cooking_oil, '16', 'g', '炒制', 0, 0, NULL, 141.44, 'seasoning');

-- Recipe 49: 青椒肉片土豆丝
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '青椒肉片土豆丝',
    '土豆丝与猪肉片、青椒同炒，香辣爽脆。',
    'https://images.example.com/qingjiao_roupian_tudousi.jpg',
    'https://videos.example.com/qingjiao_roupian_tudousi.mp4',
    18, 2, 'medium', @cuisine_sichuan,
    500.00, 36.00, 30.00, 22.00
);
SET @recipe_pork_potato_pepper := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pork_potato_pepper, 1, '腌制',
    '猪里脊切薄片加酱油、淀粉腌 6 分钟，土豆切丝泡水，青椒切丝。',
    6, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '土豆丝泡水去淀粉可保持脆爽。'
);
SET @step_pork_potato_pepper_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pork_potato_pepper_1, @tool_board, '切丝'),
    (@step_pork_potato_pepper_1, @tool_knife, '切丝'),
    (@step_pork_potato_pepper_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pork_potato_pepper, 2, '滑炒',
    '热锅倒油，下肉片滑炒 1.5 分钟至熟盛出。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '肉片单层铺开加热更均匀。'
);
SET @step_pork_potato_pepper_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pork_potato_pepper_2, @tool_wok, '滑炒'),
    (@step_pork_potato_pepper_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pork_potato_pepper, 3, '合炒',
    '锅内留油，下蒜姜末、豆瓣酱炒香，倒入土豆丝与青椒丝翻炒 2 分钟，再加入肉片、酱油、米醋和盐快速翻匀。',
    3, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '全程大火保持土豆爽脆。'
);
SET @step_pork_potato_pepper_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pork_potato_pepper_3, @tool_wok, '翻炒'),
    (@step_pork_potato_pepper_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_pork_potato_pepper, @ing_pork_loin, '260', 'g', '切片腌制', 6, 1, NULL, 371.80, 'main'),
    (@recipe_pork_potato_pepper, @ing_potato, '280', 'g', '切丝', 4, 0, NULL, 215.60, 'auxiliary'),
    (@recipe_pork_potato_pepper, @ing_green_pepper, '100', 'g', '切丝', 2, 0, NULL, 20.00, 'auxiliary'),
    (@recipe_pork_potato_pepper, @ing_garlic, '10', 'g', '切末', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_pork_potato_pepper, @ing_ginger, '8', 'g', '切末', 1, 0, NULL, 6.40, 'seasoning'),
    (@recipe_pork_potato_pepper, @ing_douban, '14', 'g', '炒香', 1, 0, NULL, 25.90, 'seasoning'),
    (@recipe_pork_potato_pepper, @ing_soy_sauce, '14', 'ml', '调味', 0, 0, NULL, 10.08, 'seasoning'),
    (@recipe_pork_potato_pepper, @ing_vinegar, '6', 'ml', '提味', 0, 0, NULL, 1.08, 'seasoning'),
    (@recipe_pork_potato_pepper, @ing_cornstarch, '10', 'g', '腌制', 1, 0, NULL, 38.10, 'seasoning'),
    (@recipe_pork_potato_pepper, @ing_cooking_oil, '18', 'g', '炒制', 0, 0, NULL, 159.12, 'seasoning'),
    (@recipe_pork_potato_pepper, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 50: 西葫芦虾仁
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '西葫芦虾仁',
    '西葫芦与虾仁快炒，口感清甜鲜嫩，热量较低。',
    'https://images.example.com/xihulu_xiaren.jpg',
    'https://videos.example.com/xihulu_xiaren.mp4',
    14, 2, 'easy', @cuisine_home,
    320.00, 30.00, 14.00, 12.00
);
SET @recipe_zucchini_shrimp := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_zucchini_shrimp, 1, '准备',
    '虾仁去虾线加盐和淀粉腌 4 分钟，西葫芦切薄片，蒜姜切末。',
    4, '常温', JSON_ARRAY('搅拌碗', '砧板', '菜刀'),
    '西葫芦切斜片可提高受热面积。'
);
SET @step_zucchini_shrimp_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_zucchini_shrimp_1, @tool_mix_bowl, '腌制'),
    (@step_zucchini_shrimp_1, @tool_board, '切片'),
    (@step_zucchini_shrimp_1, @tool_knife, '切片');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_zucchini_shrimp, 2, '滑炒',
    '热锅倒油，下虾仁滑炒 1 分钟盛出。',
    1, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '虾仁刚变色就取出保持弹嫩。'
);
SET @step_zucchini_shrimp_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_zucchini_shrimp_2, @tool_wok, '滑炒'),
    (@step_zucchini_shrimp_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_zucchini_shrimp, 3, '合炒',
    '锅内留油，下蒜姜末与西葫芦片翻炒 2 分钟，倒入虾仁，调入酱油、白砂糖与香油翻匀出锅。',
    2, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '西葫芦保持微微出水即可，避免过软。'
);
SET @step_zucchini_shrimp_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_zucchini_shrimp_3, @tool_wok, '翻炒'),
    (@step_zucchini_shrimp_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_zucchini_shrimp, @ing_zucchini, '320', 'g', '切片', 3, 1, NULL, 54.40, 'main'),
    (@recipe_zucchini_shrimp, @ing_shrimp, '200', 'g', '腌制', 4, 0, NULL, 190.00, 'auxiliary'),
    (@recipe_zucchini_shrimp, @ing_garlic, '10', 'g', '切末', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_zucchini_shrimp, @ing_ginger, '6', 'g', '切末', 1, 0, NULL, 4.80, 'seasoning'),
    (@recipe_zucchini_shrimp, @ing_soy_sauce, '10', 'ml', '调味', 0, 0, NULL, 7.20, 'seasoning'),
    (@recipe_zucchini_shrimp, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_zucchini_shrimp, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_zucchini_shrimp, @ing_cornstarch, '6', 'g', '腌制', 1, 0, NULL, 22.86, 'seasoning'),
    (@recipe_zucchini_shrimp, @ing_cooking_oil, '14', 'g', '炒制', 0, 0, NULL, 123.76, 'seasoning'),
    (@recipe_zucchini_shrimp, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 51: 黑椒杏鲍菇牛柳
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '黑椒杏鲍菇牛柳',
    '牛柳搭配杏鲍菇快速翻炒，黑椒香气浓郁，口感弹嫩。',
    'https://images.example.com/heijiao_xingbaogu_niuliu.jpg',
    'https://videos.example.com/heijiao_xingbaogu_niuliu.mp4',
    24, 2, 'medium', @cuisine_home,
    560.00, 44.00, 22.00, 30.00
);
SET @recipe_pepper_beef_mushroom := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pepper_beef_mushroom, 1, '腌制',
    '牛里脊切条加入 18ml 酱油、12g 玉米淀粉、4ml 香油与 4ml 柠檬汁抓匀腌 8 分钟；杏鲍菇切条，青椒切丝。',
    8, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '加入少量柠檬汁能提升肉香并保持颜色。'
);
SET @step_pepper_beef_mushroom_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pepper_beef_mushroom_1, @tool_board, '切条'),
    (@step_pepper_beef_mushroom_1, @tool_knife, '切条'),
    (@step_pepper_beef_mushroom_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pepper_beef_mushroom, 2, '滑炒',
    '热锅倒入 18g 食用油，将牛柳滑散 2 分钟至九成熟盛出。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '滑炒时不断翻动保持均匀受热。'
);
SET @step_pepper_beef_mushroom_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pepper_beef_mushroom_2, @tool_wok, '滑炒'),
    (@step_pepper_beef_mushroom_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pepper_beef_mushroom, 3, '合炒',
    '锅内留油，下蒜末与杏鲍菇翻炒 2 分钟，再加入青椒丝、牛柳与 10g 黑胡椒碎、6ml 酱油、3g 盐，快速翻匀即可。',
    4, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '出锅前可加入 8ml 水淀粉让酱汁更附着。'
);
SET @step_pepper_beef_mushroom_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_pepper_beef_mushroom_3, @tool_wok, '翻炒'),
    (@step_pepper_beef_mushroom_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_pepper_beef_mushroom, @ing_beef_tenderloin, '320', 'g', '切条腌制', 8, 1, NULL, 573.00, 'main'),
    (@recipe_pepper_beef_mushroom, @ing_king_oyster, '180', 'g', '切条', 3, 0, NULL, 63.00, 'auxiliary'),
    (@recipe_pepper_beef_mushroom, @ing_green_pepper, '120', 'g', '切丝', 2, 0, NULL, 24.00, 'auxiliary'),
    (@recipe_pepper_beef_mushroom, @ing_garlic, '12', 'g', '切末', 2, 0, NULL, 17.88, 'seasoning'),
    (@recipe_pepper_beef_mushroom, @ing_black_pepper, '10', 'g', '碾碎', 0, 0, NULL, 25.50, 'seasoning'),
    (@recipe_pepper_beef_mushroom, @ing_soy_sauce, '24', 'ml', '腌制/调味', 0, 0, NULL, 17.28, 'seasoning'),
    (@recipe_pepper_beef_mushroom, @ing_cornstarch, '12', 'g', '腌制', 1, 0, NULL, 45.72, 'seasoning'),
    (@recipe_pepper_beef_mushroom, @ing_sesame_oil, '4', 'ml', '腌制', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_pepper_beef_mushroom, @ing_cooking_oil, '22', 'g', '炒制', 0, 0, NULL, 194.48, 'seasoning'),
    (@recipe_pepper_beef_mushroom, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 52: 柠檬蒸虾仁
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '柠檬蒸虾仁',
    '虾仁搭配柠檬蒸制，保持原汁鲜味，低油健康。',
    'https://images.example.com/ningmeng_zheng_xiaren.jpg',
    'https://videos.example.com/ningmeng_zheng_xiaren.mp4',
    16, 2, 'easy', @cuisine_cantonese,
    210.00, 36.00, 6.00, 4.00
);
SET @recipe_lemon_steam_shrimp := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_lemon_steam_shrimp, 1, '腌制',
    '虾仁加入 2g 盐、6ml 柠檬汁、6g 玉米淀粉与 2ml 香油抓匀腌 5 分钟。',
    5, '常温', JSON_ARRAY('搅拌碗'),
    '轻轻按摩虾仁让柠檬汁均匀渗入。'
);
SET @step_lemon_steam_shrimp_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_lemon_steam_shrimp_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_lemon_steam_shrimp, 2, '摆盘',
    '粉丝泡软铺于盘底，虾仁摆在上方，撒入姜丝与柠檬片。',
    2, '常温', JSON_ARRAY('腌制碗'),
    '粉丝铺底可吸收蒸汁，风味更佳。'
);
SET @step_lemon_steam_shrimp_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_lemon_steam_shrimp_2, @tool_marinade_bowl, '摆盘');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_lemon_steam_shrimp, 3, '蒸制',
    '蒸锅水开后蒸 7 分钟，出锅时淋 4ml 香油与 6ml 蒸鱼豉油。',
    7, '大火', JSON_ARRAY('蒸锅'),
    '蒸制时间视虾仁大小微调，避免过熟。'
);
SET @step_lemon_steam_shrimp_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_lemon_steam_shrimp_3, @tool_steamer, '蒸制');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_lemon_steam_shrimp, @ing_shrimp, '240', 'g', '腌制', 5, 1, NULL, 228.00, 'main'),
    (@recipe_lemon_steam_shrimp, @ing_vermicelli, '80', 'g', '泡软', 4, 0, NULL, 265.60, 'auxiliary'),
    (@recipe_lemon_steam_shrimp, @ing_lemon, '1', '个', '切片', 1, 0, NULL, 29.00, 'auxiliary'),
    (@recipe_lemon_steam_shrimp, @ing_ginger, '12', 'g', '切丝', 2, 0, NULL, 9.60, 'seasoning'),
    (@recipe_lemon_steam_shrimp, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_lemon_steam_shrimp, @ing_cornstarch, '6', 'g', '腌制', 1, 0, NULL, 22.86, 'seasoning'),
    (@recipe_lemon_steam_shrimp, @ing_sesame_oil, '6', 'ml', '调味', 0, 0, NULL, 53.04, 'seasoning'),
    (@recipe_lemon_steam_shrimp, @ing_steaming_sauce, '6', 'ml', '调味', 0, 0, NULL, 4.32, 'seasoning');

-- Recipe 53: 香葱牛肉煎饼
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '香葱牛肉煎饼',
    '以牛肉末、香葱和面糊煎成薄饼，外脆里嫩，适合早餐或加餐。',
    'https://images.example.com/xiangcong_niurou_jianbing.jpg',
    'https://videos.example.com/xiangcong_niurou_jianbing.mp4',
    28, 3, 'medium', @cuisine_home,
    520.00, 34.00, 48.00, 18.00
);
SET @recipe_beef_pancake := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_beef_pancake, 1, '调糊',
    '碗中放 120g 面粉、12g 玉米淀粉、1 个鸡蛋、230ml 清水搅拌成稠糊，加入 6g 盐、4g 黑胡椒、20g 香葱末与 120g 牛肉末拌匀。',
    5, '常温', JSON_ARRAY('搅拌碗'),
    '面糊静置 10 分钟让面粉充分吸水。'
);
SET @step_beef_pancake_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_beef_pancake_1, @tool_mix_bowl, '调糊');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_beef_pancake, 2, '煎饼',
    '平底锅刷 10g 油，中火倒入一勺面糊摊平，煎 3 分钟翻面再煎 2 分钟至两面金黄。',
    5, '中火', JSON_ARRAY('平底锅', '锅铲'),
    '面糊宜薄不宜厚，能保证饼体熟透。'
);
SET @step_beef_pancake_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_beef_pancake_2, @tool_flat_pan, '煎制'),
    (@step_beef_pancake_2, @tool_spatula, '翻面');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_beef_pancake, 3, '调味',
    '出锅后刷少许蒸鱼豉油与辣椒粉，可按口味加入香菜末点缀。',
    1, '常温', JSON_ARRAY('平底锅'),
    '调味料趁热刷上更易附着。'
);
SET @step_beef_pancake_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_beef_pancake_3, @tool_flat_pan, '调味');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_beef_pancake, @ing_beef_tenderloin, '120', 'g', '切末', 3, 1, NULL, 214.80, 'main'),
    (@recipe_beef_pancake, @ing_egg, '1', '个', '打散', 1, 0, NULL, 143.00, 'auxiliary'),
    (@recipe_beef_pancake, @ing_scallion, '20', 'g', '切末', 2, 0, NULL, 6.40, 'auxiliary'),
    (@recipe_beef_pancake, @ing_salt, '6', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_beef_pancake, @ing_black_pepper, '4', 'g', '调味', 0, 0, NULL, 10.20, 'seasoning'),
    (@recipe_beef_pancake, @ing_sesame_oil, '4', 'ml', '调味', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_beef_pancake, @ing_cooking_oil, '20', 'g', '煎制', 0, 0, NULL, 176.80, 'seasoning'),
    (@recipe_beef_pancake, @ing_steaming_sauce, '6', 'ml', '刷味', 0, 0, NULL, 4.32, 'seasoning'),
    (@recipe_beef_pancake, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning');

-- Recipe 54: 西兰花牛肉粒
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '西兰花牛肉粒',
    '西兰花与牛肉粒快炒，保留咬劲与鲜甜口感。',
    'https://images.example.com/xilanhua_niurouli.jpg',
    'https://videos.example.com/xilanhua_niurouli.mp4',
    22, 2, 'medium', @cuisine_home,
    520.00, 46.00, 20.00, 28.00
);
SET @recipe_broccoli_beef_cubes := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_broccoli_beef_cubes, 1, '腌制',
    '牛里脊切成 1.5cm 小块，加入 18ml 酱油、10g 玉米淀粉与 4ml 香油抓匀腌 6 分钟；西兰花掰小朵焯水备用，蒜切末。',
    6, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗', '汤锅'),
    '焯水时间控制在 60 秒保持脆感。'
);
SET @step_broccoli_beef_cubes_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_broccoli_beef_cubes_1, @tool_board, '切块'),
    (@step_broccoli_beef_cubes_1, @tool_knife, '切块'),
    (@step_broccoli_beef_cubes_1, @tool_mix_bowl, '腌制'),
    (@step_broccoli_beef_cubes_1, @tool_soup_pot, '焯烫');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_broccoli_beef_cubes, 2, '滑炒',
    '热锅倒入 18g 食用油，下牛肉粒快速翻炒 2 分钟至表面焦黄盛出。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '牛肉粒翻面要迅速，避免内部过熟。'
);
SET @step_broccoli_beef_cubes_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_broccoli_beef_cubes_2, @tool_wok, '滑炒'),
    (@step_broccoli_beef_cubes_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_broccoli_beef_cubes, 3, '合炒',
    '锅内留油，下蒜末炒香，倒入西兰花与牛肉粒，调入 3g 盐、8ml 酱油和 4g 白砂糖，翻炒 2 分钟即可。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '出锅前可洒少许黑胡椒增加风味。'
);
SET @step_broccoli_beef_cubes_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_broccoli_beef_cubes_3, @tool_wok, '翻炒'),
    (@step_broccoli_beef_cubes_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_broccoli_beef_cubes, @ing_beef_tenderloin, '320', 'g', '切块腌制', 6, 1, NULL, 573.00, 'main'),
    (@recipe_broccoli_beef_cubes, @ing_broccoli, '260', 'g', '焯烫', 3, 0, NULL, 88.40, 'auxiliary'),
    (@recipe_broccoli_beef_cubes, @ing_garlic, '12', 'g', '切末', 1, 0, NULL, 17.88, 'seasoning'),
    (@recipe_broccoli_beef_cubes, @ing_soy_sauce, '26', 'ml', '腌制/调味', 0, 0, NULL, 18.72, 'seasoning'),
    (@recipe_broccoli_beef_cubes, @ing_cornstarch, '10', 'g', '腌制', 1, 0, NULL, 38.10, 'seasoning'),
    (@recipe_broccoli_beef_cubes, @ing_sesame_oil, '4', 'ml', '腌制', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_broccoli_beef_cubes, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_broccoli_beef_cubes, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_broccoli_beef_cubes, @ing_cooking_oil, '20', 'g', '炒制', 0, 0, NULL, 176.80, 'seasoning');

-- Recipe 55: 花生土豆鸡丁
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '花生土豆鸡丁',
    '鸡丁搭配花生与土豆粒，先煎后拌，香酥微辣，适合配饭。',
    'https://images.example.com/huasheng_tudou_jiding.jpg',
    'https://videos.example.com/huasheng_tudou_jiding.mp4',
    28, 3, 'medium', @cuisine_home,
    640.00, 42.00, 38.00, 34.00
);
SET @recipe_peanut_potato_chicken := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_peanut_potato_chicken, 1, '切配',
    '鸡胸肉切 1.5cm 小丁，加入 16ml 酱油、10g 玉米淀粉与 3g 盐腌 8 分钟；土豆切小丁泡水去淀粉，蒜姜切末，干辣椒剪段。',
    8, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '土豆丁浸泡 5 分钟可降低淀粉并保持外酥内糯。'
);
SET @step_peanut_potato_chicken_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_peanut_potato_chicken_1, @tool_board, '切丁'),
    (@step_peanut_potato_chicken_1, @tool_knife, '切丁'),
    (@step_peanut_potato_chicken_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_peanut_potato_chicken, 2, '煎香',
    '平底锅倒入 22g 食用油，先煎鸡丁 3 分钟至表面金黄盛出，再下土豆丁煎 4 分钟至外脆，加入花生米与干辣椒翻炒 1 分钟。',
    8, '中火', JSON_ARRAY('平底锅', '锅铲'),
    '煎制时保持中火，逐次翻面保证受热均匀。'
);
SET @step_peanut_potato_chicken_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_peanut_potato_chicken_2, @tool_flat_pan, '煎制'),
    (@step_peanut_potato_chicken_2, @tool_spatula, '翻动');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_peanut_potato_chicken, 3, '合炒',
    '将所有食材倒入炒锅，加入蒜姜末、6g 白砂糖、10ml 米醋与 6ml 香油，大火翻炒 2 分钟，让酱汁裹匀即可。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '最后 30 秒持续翻炒，保证花生保持酥脆。'
);
SET @step_peanut_potato_chicken_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_peanut_potato_chicken_3, @tool_wok, '翻炒'),
    (@step_peanut_potato_chicken_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_peanut_potato_chicken, @ing_chicken, '360', 'g', '切丁腌制', 8, 1, NULL, 576.00, 'main'),
    (@recipe_peanut_potato_chicken, @ing_potato, '220', 'g', '切丁', 4, 0, NULL, 169.40, 'auxiliary'),
    (@recipe_peanut_potato_chicken, @ing_peanut, '70', 'g', '生花生炒香', 2, 0, NULL, 396.90, 'auxiliary'),
    (@recipe_peanut_potato_chicken, @ing_garlic, '12', 'g', '切末', 1, 0, NULL, 17.88, 'seasoning'),
    (@recipe_peanut_potato_chicken, @ing_ginger, '10', 'g', '切末', 1, 0, NULL, 8.00, 'seasoning'),
    (@recipe_peanut_potato_chicken, @ing_dried_chili, '10', 'g', '剪段', 1, 0, NULL, 15.00, 'seasoning'),
    (@recipe_peanut_potato_chicken, @ing_soy_sauce, '18', 'ml', '腌制/调味', 0, 0, NULL, 12.96, 'seasoning'),
    (@recipe_peanut_potato_chicken, @ing_cornstarch, '12', 'g', '腌制', 1, 0, NULL, 45.72, 'seasoning'),
    (@recipe_peanut_potato_chicken, @ing_sugar, '6', 'g', '调味', 0, 0, NULL, 23.22, 'seasoning'),
    (@recipe_peanut_potato_chicken, @ing_vinegar, '10', 'ml', '调味', 0, 0, NULL, 1.80, 'seasoning'),
    (@recipe_peanut_potato_chicken, @ing_sesame_oil, '6', 'ml', '调味', 0, 0, NULL, 53.04, 'seasoning'),
    (@recipe_peanut_potato_chicken, @ing_cooking_oil, '26', 'g', '煎炒', 0, 0, NULL, 229.84, 'seasoning'),
    (@recipe_peanut_potato_chicken, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 56: 酸辣青豆玉米粒
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '酸辣青豆玉米粒',
    '青豆与玉米粒搭配酸辣调味，口感爽脆，适合作为开胃小菜。',
    'https://images.example.com/suanla_qingdou_yumili.jpg',
    'https://videos.example.com/suanla_qingdou_yumili.mp4',
    12, 2, 'easy', @cuisine_home,
    240.00, 12.00, 34.00, 6.00
);
SET @recipe_spicy_pea_corn := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_spicy_pea_corn, 1, '焯烫',
    '玉米粒与青豆入沸水焯 45 秒，捞出沥干备用。',
    1, '大火', JSON_ARRAY('汤锅'),
    '焯烫后立即过凉水可保持色泽鲜亮。'
);
SET @step_spicy_pea_corn_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_spicy_pea_corn_1, @tool_soup_pot, '焯烫');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_spicy_pea_corn, 2, '爆香',
    '热锅倒入 12g 食用油，下蒜末和干辣椒段小火炒香 40 秒。',
    1, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '香料炒出香味后立即加入主料防止糊锅。'
);
SET @step_spicy_pea_corn_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_spicy_pea_corn_2, @tool_wok, '爆香'),
    (@step_spicy_pea_corn_2, @tool_spatula, '翻动');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_spicy_pea_corn, 3, '快炒',
    '倒入玉米粒与青豆，调入 4g 盐、8ml 米醋、6g 白砂糖与 3g 花椒粉，大火翻炒 2 分钟，最后淋上 4ml 香油。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '出锅前快速翻匀让酸辣味均匀包裹。'
);
SET @step_spicy_pea_corn_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_spicy_pea_corn_3, @tool_wok, '翻炒'),
    (@step_spicy_pea_corn_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_spicy_pea_corn, @ing_corn_kernel, '200', 'g', '焯烫', 1, 1, NULL, 172.00, 'main'),
    (@recipe_spicy_pea_corn, @ing_green_pea, '150', 'g', '焯烫', 1, 0, NULL, 177.00, 'auxiliary'),
    (@recipe_spicy_pea_corn, @ing_garlic, '10', 'g', '切末', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_spicy_pea_corn, @ing_dried_chili, '6', 'g', '剪段', 1, 0, NULL, 9.00, 'seasoning'),
    (@recipe_spicy_pea_corn, @ing_vinegar, '8', 'ml', '调味', 0, 0, NULL, 1.44, 'seasoning'),
    (@recipe_spicy_pea_corn, @ing_sugar, '6', 'g', '调味', 0, 0, NULL, 23.22, 'seasoning'),
    (@recipe_spicy_pea_corn, @ing_sichuan_pepper, '3', 'g', '调味', 0, 0, NULL, 9.00, 'seasoning'),
    (@recipe_spicy_pea_corn, @ing_salt, '4', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_spicy_pea_corn, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_spicy_pea_corn, @ing_cooking_oil, '12', 'g', '爆香', 0, 0, NULL, 106.08, 'seasoning');

-- Recipe 57: 番茄虾仁汤
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '番茄虾仁汤',
    '番茄与虾仁熬成微酸汤品，加入少量鸡蛋增添口感。',
    'https://images.example.com/fanqie_xiaren_tang.jpg',
    'https://videos.example.com/fanqie_xiaren_tang.mp4',
    18, 3, 'easy', @cuisine_home,
    280.00, 30.00, 16.00, 8.00
);
SET @recipe_tomato_shrimp_soup := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_tomato_shrimp_soup, 1, '备料',
    '虾仁用 2g 盐和 4g 玉米淀粉腌 3 分钟，番茄切丁，鸡蛋打散，小葱切末。',
    4, '常温', JSON_ARRAY('搅拌碗', '砧板', '菜刀'),
    '番茄先去籽能让汤体更清澈。'
);
SET @step_tomato_shrimp_soup_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_tomato_shrimp_soup_1, @tool_mix_bowl, '腌制/打蛋'),
    (@step_tomato_shrimp_soup_1, @tool_board, '切丁'),
    (@step_tomato_shrimp_soup_1, @tool_knife, '切丁');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_tomato_shrimp_soup, 2, '煸香',
    '汤锅加入 8g 食用油，下番茄丁煸 2 分钟至出汁。',
    2, '中火', JSON_ARRAY('汤锅'),
    '煸香后再加水味道更浓郁。'
);
SET @step_tomato_shrimp_soup_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_tomato_shrimp_soup_2, @tool_soup_pot, '煸香');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_tomato_shrimp_soup, 3, '煮汤',
    '倒入 700ml 清水煮沸后加入虾仁煮 2 分钟，缓缓倒入蛋液搅拌成蛋花，调入 4g 盐与 4g 白砂糖，撒上小葱即可。',
    4, '中火', JSON_ARRAY('汤锅'),
    '蛋花入锅时保持环形搅动防止成团。'
);
SET @step_tomato_shrimp_soup_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_tomato_shrimp_soup_3, @tool_soup_pot, '煮汤');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_tomato_shrimp_soup, @ing_shrimp, '220', 'g', '腌制', 3, 1, NULL, 209.00, 'main'),
    (@recipe_tomato_shrimp_soup, @ing_tomato, '320', 'g', '切丁', 3, 0, NULL, 57.60, 'auxiliary'),
    (@recipe_tomato_shrimp_soup, @ing_egg, '1', '个', '打散', 1, 0, NULL, 143.00, 'auxiliary'),
    (@recipe_tomato_shrimp_soup, @ing_scallion, '10', 'g', '切末', 1, 0, NULL, 3.20, 'seasoning'),
    (@recipe_tomato_shrimp_soup, @ing_cornstarch, '4', 'g', '腌制', 1, 0, NULL, 15.24, 'seasoning'),
    (@recipe_tomato_shrimp_soup, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_tomato_shrimp_soup, @ing_salt, '4', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_tomato_shrimp_soup, @ing_cooking_oil, '8', 'g', '煸香', 0, 0, NULL, 70.88, 'seasoning');

-- Recipe 58: 西葫芦豆腐煲
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '西葫芦豆腐煲',
    '西葫芦与嫩豆腐小火焖煮，汤汁清淡，富含蔬菜纤维。',
    'https://images.example.com/xihulu_doufubao.jpg',
    'https://videos.example.com/xihulu_doufubao.mp4',
    20, 2, 'easy', @cuisine_home,
    260.00, 20.00, 18.00, 10.00
);
SET @recipe_zucchini_tofu_casserole := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_zucchini_tofu_casserole, 1, '切配',
    '西葫芦切滚刀块，嫩豆腐切 2cm 方块，蒜切片，姜切丝。',
    4, '常温', JSON_ARRAY('砧板', '菜刀'),
    '豆腐切块后用热水冲洗 20 秒可去腥。'
);
SET @step_zucchini_tofu_casserole_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_zucchini_tofu_casserole_1, @tool_board, '切块'),
    (@step_zucchini_tofu_casserole_1, @tool_knife, '切块');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_zucchini_tofu_casserole, 2, '煸香',
    '炒锅倒入 12g 食用油，下蒜片和姜丝煸香，加入西葫芦块翻炒 2 分钟。',
    2, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '西葫芦先炒出香味再焖煮更入味。'
);
SET @step_zucchini_tofu_casserole_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_zucchini_tofu_casserole_2, @tool_wok, '翻炒'),
    (@step_zucchini_tofu_casserole_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_zucchini_tofu_casserole, 3, '焖煮',
    '加入豆腐块、400ml 清水与 6ml 酱油、3g 盐，小火焖煮 6 分钟，出锅前淋入 4ml 香油与小葱段即可。',
    6, '小火', JSON_ARRAY('炒锅', '锅铲'),
    '焖煮时轻轻推拌避免豆腐破碎。'
);
SET @step_zucchini_tofu_casserole_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_zucchini_tofu_casserole_3, @tool_wok, '焖煮'),
    (@step_zucchini_tofu_casserole_3, @tool_spatula, '轻推');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_zucchini_tofu_casserole, @ing_zucchini, '340', 'g', '切块', 3, 1, NULL, 57.80, 'main'),
    (@recipe_zucchini_tofu_casserole, @ing_soft_tofu, '380', 'g', '切块', 2, 0, NULL, 266.00, 'auxiliary'),
    (@recipe_zucchini_tofu_casserole, @ing_garlic, '10', 'g', '切片', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_zucchini_tofu_casserole, @ing_ginger, '8', 'g', '切丝', 1, 0, NULL, 6.40, 'seasoning'),
    (@recipe_zucchini_tofu_casserole, @ing_soy_sauce, '6', 'ml', '调味', 0, 0, NULL, 4.32, 'seasoning'),
    (@recipe_zucchini_tofu_casserole, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_zucchini_tofu_casserole, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_zucchini_tofu_casserole, @ing_scallion, '10', 'g', '切段', 1, 0, NULL, 3.20, 'seasoning'),
    (@recipe_zucchini_tofu_casserole, @ing_cooking_oil, '12', 'g', '煸香', 0, 0, NULL, 106.08, 'seasoning');

-- Recipe 59: 葱香牛腩汤
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '葱香牛腩汤',
    '牛腩与大量小葱慢炖，汤汁醇厚，适合冬季暖身。',
    'https://images.example.com/congxiang_niunan_tang.jpg',
    'https://videos.example.com/congxiang_niunan_tang.mp4',
    90, 4, 'medium', @cuisine_home,
    980.00, 84.00, 24.00, 62.00
);
SET @recipe_scallion_brisket_soup := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_scallion_brisket_soup, 1, '焯水',
    '牛腩冷水下锅，加姜片与 12ml 料酒，煮沸后撇去浮沫，捞出冲净。',
    12, '大火', JSON_ARRAY('汤锅'),
    '焯水后用温水冲洗能去除残余血沫。'
);
SET @step_scallion_brisket_soup_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_scallion_brisket_soup_1, @tool_soup_pot, '焯水');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_scallion_brisket_soup, 2, '炖煮',
    '汤锅重新加入 1.2L 清水，放入牛腩、60g 小葱段与姜片，小火慢炖 70 分钟。',
    70, '小火', JSON_ARRAY('汤锅'),
    '期间每 20 分钟撇除表面油脂，汤体更清爽。'
);
SET @step_scallion_brisket_soup_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_scallion_brisket_soup_2, @tool_soup_pot, '炖煮');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_scallion_brisket_soup, 3, '调味',
    '加入 6g 盐与 4g 白砂糖，再炖 8 分钟，出锅前撒上 20g 小葱末即可。',
    8, '小火', JSON_ARRAY('汤锅'),
    '最后调味后再小火焖几分钟让葱香释放。'
);
SET @step_scallion_brisket_soup_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_scallion_brisket_soup_3, @tool_soup_pot, '调味');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_scallion_brisket_soup, @ing_brisket, '780', 'g', '焯水', 12, 1, NULL, 1248.00, 'main'),
    (@recipe_scallion_brisket_soup, @ing_scallion, '80', 'g', '切段', 3, 0, NULL, 25.60, 'auxiliary'),
    (@recipe_scallion_brisket_soup, @ing_ginger, '14', 'g', '切片', 1, 0, NULL, 11.20, 'seasoning'),
    (@recipe_scallion_brisket_soup, @ing_shaoxing_wine, '12', 'ml', '焯水', 0, 0, NULL, 6.24, 'seasoning'),
    (@recipe_scallion_brisket_soup, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_scallion_brisket_soup, @ing_salt, '6', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning');

-- Recipe 60: 柠檬炖鸡腿
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '柠檬炖鸡腿',
    '鸡腿肉与柠檬、番茄慢炖，汤汁清新，肉质软嫩。',
    'https://images.example.com/ningmeng_dun_jitui.jpg',
    'https://videos.example.com/ningmeng_dun_jitui.mp4',
    45, 3, 'easy', @cuisine_home,
    580.00, 52.00, 20.00, 32.00
);
SET @recipe_lemon_braised_chicken := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_lemon_braised_chicken, 1, '腌制',
    '鸡腿肉切块加入 18ml 酱油、8ml 柠檬汁与 6g 玉米淀粉抓匀腌 10 分钟，番茄切块，柠檬切片。',
    10, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '腌制时加入柠檬皮屑可增强果香。'
);
SET @step_lemon_braised_chicken_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_lemon_braised_chicken_1, @tool_board, '切块'),
    (@step_lemon_braised_chicken_1, @tool_knife, '切块'),
    (@step_lemon_braised_chicken_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_lemon_braised_chicken, 2, '煸香',
    '炒锅倒入 16g 食用油，下蒜片和姜丝煸香，加入鸡腿块煎 4 分钟至表面微焦。',
    4, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '鸡肉煎至微焦可锁住肉汁。'
);
SET @step_lemon_braised_chicken_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_lemon_braised_chicken_2, @tool_wok, '煸香'),
    (@step_lemon_braised_chicken_2, @tool_spatula, '翻面');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_lemon_braised_chicken, 3, '炖煮',
    '倒入番茄块、柠檬片与 500ml 清水，加入 4g 白砂糖与 4g 盐，小火炖 25 分钟，最后淋入 4ml 香油即可。',
    25, '小火', JSON_ARRAY('炒锅', '锅铲'),
    '炖煮过程中保持小火，汤汁更清透。'
);
SET @step_lemon_braised_chicken_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_lemon_braised_chicken_3, @tool_wok, '炖煮'),
    (@step_lemon_braised_chicken_3, @tool_spatula, '轻推');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_lemon_braised_chicken, @ing_chicken_leg, '600', 'g', '切块腌制', 10, 1, NULL, 1062.00, 'main'),
    (@recipe_lemon_braised_chicken, @ing_lemon, '1', '个', '切片', 1, 0, NULL, 29.00, 'auxiliary'),
    (@recipe_lemon_braised_chicken, @ing_tomato, '260', 'g', '切块', 2, 0, NULL, 46.80, 'auxiliary'),
    (@recipe_lemon_braised_chicken, @ing_garlic, '10', 'g', '切片', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_lemon_braised_chicken, @ing_ginger, '10', 'g', '切丝', 1, 0, NULL, 8.00, 'seasoning'),
    (@recipe_lemon_braised_chicken, @ing_soy_sauce, '18', 'ml', '腌制', 0, 0, NULL, 12.96, 'seasoning'),
    (@recipe_lemon_braised_chicken, @ing_cornstarch, '6', 'g', '腌制', 1, 0, NULL, 22.86, 'seasoning'),
    (@recipe_lemon_braised_chicken, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_lemon_braised_chicken, @ing_salt, '4', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_lemon_braised_chicken, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning'),
(@recipe_lemon_braised_chicken, @ing_cooking_oil, '16', 'g', '煸香', 0, 0, NULL, 141.44, 'seasoning');
-- Recipe 61: 黑椒土豆虾仁
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '黑椒土豆虾仁',
    '黑胡椒与土豆、虾仁一同翻炒，外酥里嫩，椒香浓郁。',
    'https://images.example.com/heijiao_tudou_xiaren.jpg',
    'https://videos.example.com/heijiao_tudou_xiaren.mp4',
    20, 2, 'medium', @cuisine_home,
    440.00, 34.00, 26.00, 20.00
);
SET @recipe_pepper_potato_shrimp := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pepper_potato_shrimp, 1, '腌制',
    '虾仁加入 2g 盐、8ml 柠檬汁与 6g 玉米淀粉抓匀腌 4 分钟；土豆切成 0.5cm 厚片放入清水浸泡，蒜姜切末。',
    4, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '土豆片浸泡可避免炒制时粘连。'
);
SET @step_recipe_pepper_potato_shrimp_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_pepper_potato_shrimp_1, @tool_board, '切片'),
    (@step_recipe_pepper_potato_shrimp_1, @tool_knife, '切片'),
    (@step_recipe_pepper_potato_shrimp_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pepper_potato_shrimp, 2, '煎香',
    '平底锅倒入 18g 食用油，中火煎土豆片 3 分钟至两面金黄，加入虾仁快速翻煎 1 分钟至变色盛出。',
    4, '中火', JSON_ARRAY('平底锅', '锅铲'),
    '土豆片煎至微焦更能吸附黑胡椒香气。'
);
SET @step_recipe_pepper_potato_shrimp_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_pepper_potato_shrimp_2, @tool_flat_pan, '煎制'),
    (@step_recipe_pepper_potato_shrimp_2, @tool_spatula, '翻面');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_pepper_potato_shrimp, 3, '合炒',
    '炒锅内加入 10g 食用油，下蒜姜末与 8g 黑胡椒碎爆香，倒入土豆片和虾仁，调入 6ml 酱油、4g 白砂糖与 2g 盐，大火翻炒 2 分钟，最后淋上 4ml 香油。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '黑胡椒需在油中短暂爆香，味道更加持久。'
);
SET @step_recipe_pepper_potato_shrimp_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_pepper_potato_shrimp_3, @tool_wok, '翻炒'),
    (@step_recipe_pepper_potato_shrimp_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_pepper_potato_shrimp, @ing_shrimp, '240', 'g', '腌制', 4, 1, NULL, 228.00, 'main'),
    (@recipe_pepper_potato_shrimp, @ing_potato, '260', 'g', '切片', 4, 0, NULL, 200.20, 'auxiliary'),
    (@recipe_pepper_potato_shrimp, @ing_garlic, '12', 'g', '切末', 1, 0, NULL, 17.88, 'seasoning'),
    (@recipe_pepper_potato_shrimp, @ing_ginger, '8', 'g', '切末', 1, 0, NULL, 6.40, 'seasoning'),
    (@recipe_pepper_potato_shrimp, @ing_black_pepper, '8', 'g', '碾碎', 0, 0, NULL, 20.40, 'seasoning'),
    (@recipe_pepper_potato_shrimp, @ing_soy_sauce, '6', 'ml', '调味', 0, 0, NULL, 4.32, 'seasoning'),
    (@recipe_pepper_potato_shrimp, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_pepper_potato_shrimp, @ing_salt, '2', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_pepper_potato_shrimp, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_pepper_potato_shrimp, @ing_cooking_oil, '28', 'g', '煎炒', 0, 0, NULL, 247.52, 'seasoning');

-- Recipe 62: 豆瓣西兰花牛腩
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '豆瓣西兰花牛腩',
    '牛腩与西兰花结合，豆瓣酱提味，辣而不燥。',
    'https://images.example.com/douban_xilanhua_niunan.jpg',
    'https://videos.example.com/douban_xilanhua_niunan.mp4',
    32, 3, 'medium', @cuisine_sichuan,
    720.00, 58.00, 24.00, 42.00
);
SET @recipe_douban_broccoli_brisket := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_douban_broccoli_brisket, 1, '焯水',
    '牛腩切薄片入沸水焯 3 分钟，捞出冲净；西兰花掰小朵焯水 50 秒备用。',
    4, '大火', JSON_ARRAY('汤锅'),
    '焯水可以去除牛腩油脂并保持西兰花翠绿。'
);
SET @step_recipe_douban_broccoli_brisket_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_douban_broccoli_brisket_1, @tool_soup_pot, '焯水');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_douban_broccoli_brisket, 2, '煸香',
    '炒锅倒入 18g 食用油，下蒜末与 18g 豆瓣酱炒出红油，加入牛腩片翻炒 3 分钟。',
    3, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '豆瓣酱需要充分煸炒才能释放香味。'
);
SET @step_recipe_douban_broccoli_brisket_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_douban_broccoli_brisket_2, @tool_wok, '煸香'),
    (@step_recipe_douban_broccoli_brisket_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_douban_broccoli_brisket, 3, '合炒',
    '倒入西兰花与 80ml 清水，加入 10ml 酱油、4g 白砂糖与 3g 盐，大火翻炒 2 分钟至汤汁浓稠。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '出锅前可撒少许黑胡椒调味。'
);
SET @step_recipe_douban_broccoli_brisket_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_douban_broccoli_brisket_3, @tool_wok, '翻炒'),
    (@step_recipe_douban_broccoli_brisket_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_douban_broccoli_brisket, @ing_brisket, '420', 'g', '焯水', 3, 1, NULL, 672.00, 'main'),
    (@recipe_douban_broccoli_brisket, @ing_broccoli, '260', 'g', '焯烫', 2, 0, NULL, 88.40, 'auxiliary'),
    (@recipe_douban_broccoli_brisket, @ing_douban, '18', 'g', '炒香', 1, 0, NULL, 33.30, 'seasoning'),
    (@recipe_douban_broccoli_brisket, @ing_garlic, '12', 'g', '切末', 1, 0, NULL, 17.88, 'seasoning'),
    (@recipe_douban_broccoli_brisket, @ing_soy_sauce, '10', 'ml', '调味', 0, 0, NULL, 7.20, 'seasoning'),
    (@recipe_douban_broccoli_brisket, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_douban_broccoli_brisket, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_douban_broccoli_brisket, @ing_cooking_oil, '20', 'g', '煸香', 0, 0, NULL, 176.80, 'seasoning');

-- Recipe 63: 香菇鸡蛋汤
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '香菇鸡蛋汤',
    '香菇与鸡蛋搭配，小火煮成清爽家常汤。',
    'https://images.example.com/xianggu_jidan_tang.jpg',
    'https://videos.example.com/xianggu_jidan_tang.mp4',
    15, 2, 'easy', @cuisine_home,
    180.00, 16.00, 10.00, 8.00
);
SET @recipe_shiitake_egg_soup := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_shiitake_egg_soup, 1, '切配',
    '香菇切丝，鸡蛋打散，小葱切末。',
    2, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '香菇切丝后撒少许盐预先入味。'
);
SET @step_recipe_shiitake_egg_soup_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_shiitake_egg_soup_1, @tool_board, '切丝'),
    (@step_recipe_shiitake_egg_soup_1, @tool_knife, '切丝'),
    (@step_recipe_shiitake_egg_soup_1, @tool_mix_bowl, '打蛋');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_shiitake_egg_soup, 2, '煸香',
    '汤锅加入 6g 食用油，下香菇丝煸香 1 分钟。',
    1, '中火', JSON_ARRAY('汤锅'),
    '香菇提前煸香汤味更浓郁。'
);
SET @step_recipe_shiitake_egg_soup_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_shiitake_egg_soup_2, @tool_soup_pot, '煸香');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_shiitake_egg_soup, 3, '煮汤',
    '倒入 600ml 清水煮沸，缓缓倒入蛋液形成蛋花，加入 3g 盐、4g 白砂糖，撒上小葱末与 4ml 香油。',
    4, '中火', JSON_ARRAY('汤锅'),
    '蛋液沿锅边缓慢倒入更易形成漂亮蛋花。'
);
SET @step_recipe_shiitake_egg_soup_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_shiitake_egg_soup_3, @tool_soup_pot, '煮汤');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_shiitake_egg_soup, @ing_shiitake, '120', 'g', '切丝', 2, 1, NULL, 40.80, 'main'),
    (@recipe_shiitake_egg_soup, @ing_egg, '2', '个', '打散', 1, 0, NULL, 286.00, 'auxiliary'),
    (@recipe_shiitake_egg_soup, @ing_scallion, '12', 'g', '切末', 1, 0, NULL, 3.84, 'seasoning'),
    (@recipe_shiitake_egg_soup, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_shiitake_egg_soup, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_shiitake_egg_soup, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_shiitake_egg_soup, @ing_cooking_oil, '6', 'g', '煸香', 0, 0, NULL, 53.04, 'seasoning');

-- Recipe 64: 花椒鸡丝
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '花椒鸡丝',
    '使用花椒与干辣椒炝锅，鸡丝鲜辣爽口，适合作为凉热皆宜的家常菜。',
    'https://images.example.com/huajiao_jisi.jpg',
    'https://videos.example.com/huajiao_jisi.mp4',
    18, 2, 'medium', @cuisine_sichuan,
    380.00, 36.00, 12.00, 18.00
);
SET @recipe_sichuan_pepper_chicken_shreds := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_sichuan_pepper_chicken_shreds, 1, '切丝',
    '鸡胸肉切细丝，加入 14ml 酱油、8g 玉米淀粉与 3ml 香油抓匀腌 6 分钟；青椒切丝，蒜切末。',
    6, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '鸡丝逆纹切可以保持嫩度。'
);
SET @step_recipe_sichuan_pepper_chicken_shreds_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_sichuan_pepper_chicken_shreds_1, @tool_board, '切丝'),
    (@step_recipe_sichuan_pepper_chicken_shreds_1, @tool_knife, '切丝'),
    (@step_recipe_sichuan_pepper_chicken_shreds_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_sichuan_pepper_chicken_shreds, 2, '炝锅',
    '炒锅倒入 16g 食用油，放入 4g 花椒与 8g 干辣椒小火炝香 50 秒。',
    1, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '花椒炝香后迅速进行下一步，避免发苦。'
);
SET @step_recipe_sichuan_pepper_chicken_shreds_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_sichuan_pepper_chicken_shreds_2, @tool_wok, '炝锅'),
    (@step_recipe_sichuan_pepper_chicken_shreds_2, @tool_spatula, '翻动');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_sichuan_pepper_chicken_shreds, 3, '快炒',
    '加入鸡丝大火翻炒 2 分钟至变色，再加入青椒丝与蒜末，调入 3g 盐和 4ml 香油，继续翻炒 1 分钟即可。',
    3, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '全程大火保持鸡丝爽滑不出水。'
);
SET @step_recipe_sichuan_pepper_chicken_shreds_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_sichuan_pepper_chicken_shreds_3, @tool_wok, '翻炒'),
    (@step_recipe_sichuan_pepper_chicken_shreds_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_sichuan_pepper_chicken_shreds, @ing_chicken, '320', 'g', '切丝腌制', 6, 1, NULL, 512.00, 'main'),
    (@recipe_sichuan_pepper_chicken_shreds, @ing_green_pepper, '100', 'g', '切丝', 2, 0, NULL, 20.00, 'auxiliary'),
    (@recipe_sichuan_pepper_chicken_shreds, @ing_garlic, '10', 'g', '切末', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_sichuan_pepper_chicken_shreds, @ing_sichuan_pepper, '4', 'g', '炝香', 0, 0, NULL, 12.00, 'seasoning'),
    (@recipe_sichuan_pepper_chicken_shreds, @ing_dried_chili, '8', 'g', '炝香', 0, 0, NULL, 12.00, 'seasoning'),
    (@recipe_sichuan_pepper_chicken_shreds, @ing_soy_sauce, '14', 'ml', '腌制', 0, 0, NULL, 10.08, 'seasoning'),
    (@recipe_sichuan_pepper_chicken_shreds, @ing_cornstarch, '8', 'g', '腌制', 1, 0, NULL, 30.48, 'seasoning'),
    (@recipe_sichuan_pepper_chicken_shreds, @ing_sesame_oil, '4', 'ml', '调味', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_sichuan_pepper_chicken_shreds, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_sichuan_pepper_chicken_shreds, @ing_cooking_oil, '20', 'g', '炒制', 0, 0, NULL, 176.80, 'seasoning');

-- Recipe 65: 香油凉拌豆腐
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '香油凉拌豆腐',
    '嫩豆腐搭配香油、米醋简单调味，凉拌口感细腻。',
    'https://images.example.com/xiangyou_liangban_doufu.jpg',
    'https://videos.example.com/xiangyou_liangban_doufu.mp4',
    8, 2, 'easy', @cuisine_home,
    210.00, 16.00, 10.00, 12.00
);
SET @recipe_chilled_tofu_sesame := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_chilled_tofu_sesame, 1, '准备',
    '嫩豆腐切 2cm 方块放入冰水浸泡 2 分钟，沥干摆盘；小葱切末，蒜切末。',
    3, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '冰水镇一下豆腐，口感更紧实。'
);
SET @step_recipe_chilled_tofu_sesame_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_chilled_tofu_sesame_1, @tool_board, '切块'),
    (@step_recipe_chilled_tofu_sesame_1, @tool_knife, '切末'),
    (@step_recipe_chilled_tofu_sesame_1, @tool_mix_bowl, '冰水浸泡');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_chilled_tofu_sesame, 2, '调汁',
    '小碗中加入 12ml 米醋、6g 白砂糖、3g 盐、4ml 香油与蒜末、葱末搅拌均匀。',
    2, '常温', JSON_ARRAY('搅拌碗'),
    '糖先与醋混合可更快溶解。'
);
SET @step_recipe_chilled_tofu_sesame_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_chilled_tofu_sesame_2, @tool_mix_bowl, '调汁');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_chilled_tofu_sesame, 3, '拌制',
    '将调好的酱汁均匀浇在豆腐上，撒上花椒粉即可食用。',
    1, '常温', JSON_ARRAY('搅拌碗'),
    '拌制时轻轻摇晃盘子即可，避免豆腐破碎。'
);
SET @step_recipe_chilled_tofu_sesame_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_chilled_tofu_sesame_3, @tool_mix_bowl, '调味');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_chilled_tofu_sesame, @ing_soft_tofu, '420', 'g', '切块', 3, 1, NULL, 294.00, 'main'),
    (@recipe_chilled_tofu_sesame, @ing_scallion, '16', 'g', '切末', 1, 0, NULL, 5.12, 'auxiliary'),
    (@recipe_chilled_tofu_sesame, @ing_garlic, '8', 'g', '切末', 1, 0, NULL, 11.92, 'seasoning'),
    (@recipe_chilled_tofu_sesame, @ing_vinegar, '12', 'ml', '调味', 0, 0, NULL, 2.16, 'seasoning'),
    (@recipe_chilled_tofu_sesame, @ing_sugar, '6', 'g', '调味', 0, 0, NULL, 23.22, 'seasoning'),
    (@recipe_chilled_tofu_sesame, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_chilled_tofu_sesame, @ing_sesame_oil, '6', 'ml', '调味', 0, 0, NULL, 53.04, 'seasoning'),
    (@recipe_chilled_tofu_sesame, @ing_sichuan_pepper, '2', 'g', '撒粉', 0, 0, NULL, 6.00, 'seasoning');

-- Recipe 66: 糖醋虾仁
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '糖醋虾仁',
    '经典糖醋口味虾仁，外层裹汁闪亮，入口酸甜。',
    'https://images.example.com/tangcu_xiaren.jpg',
    'https://videos.example.com/tangcu_xiaren.mp4',
    18, 2, 'easy', @cuisine_home,
    360.00, 34.00, 24.00, 14.00
);
SET @recipe_sweet_sour_shrimp := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_sweet_sour_shrimp, 1, '裹浆',
    '虾仁加入 10g 玉米淀粉、4g 盐与 8ml 料酒抓匀，放置 5 分钟。',
    5, '常温', JSON_ARRAY('搅拌碗'),
    '裹浆后轻拍虾仁，使多余粉末抖落。'
);
SET @step_recipe_sweet_sour_shrimp_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_sweet_sour_shrimp_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_sweet_sour_shrimp, 2, '煎炒',
    '热锅倒入 18g 食用油下虾仁滑炒 2 分钟至定型盛出。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '虾仁刚卷曲即可取出，防止过老。'
);
SET @step_recipe_sweet_sour_shrimp_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_sweet_sour_shrimp_2, @tool_wok, '滑炒'),
    (@step_recipe_sweet_sour_shrimp_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_sweet_sour_shrimp, 3, '调酱',
    '锅内留下 6g 油，加入 24g 白砂糖、20ml 米醋与 10ml 酱油，中火熬至起泡，倒入虾仁翻炒 1 分钟，最后洒上 2ml 香油。',
    1, '中火', JSON_ARRAY('炒锅', '锅铲'),
    '糖醋汁出现密集小泡即可关火。'
);
SET @step_recipe_sweet_sour_shrimp_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_sweet_sour_shrimp_3, @tool_wok, '调酱'),
    (@step_recipe_sweet_sour_shrimp_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_sweet_sour_shrimp, @ing_shrimp, '260', 'g', '裹浆', 5, 1, NULL, 247.00, 'main'),
    (@recipe_sweet_sour_shrimp, @ing_cornstarch, '10', 'g', '裹浆', 1, 0, NULL, 38.10, 'seasoning'),
    (@recipe_sweet_sour_shrimp, @ing_sugar, '24', 'g', '调味', 0, 0, NULL, 92.88, 'seasoning'),
    (@recipe_sweet_sour_shrimp, @ing_vinegar, '20', 'ml', '调味', 0, 0, NULL, 3.60, 'seasoning'),
    (@recipe_sweet_sour_shrimp, @ing_soy_sauce, '10', 'ml', '调味', 0, 0, NULL, 7.20, 'seasoning'),
    (@recipe_sweet_sour_shrimp, @ing_sesame_oil, '2', 'ml', '提香', 0, 0, NULL, 17.68, 'seasoning'),
    (@recipe_sweet_sour_shrimp, @ing_salt, '4', 'g', '腌制', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_sweet_sour_shrimp, @ing_cooking_oil, '24', 'g', '煎炒', 0, 0, NULL, 211.20, 'seasoning');

-- Recipe 67: 青椒牛腩丝
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '青椒牛腩丝',
    '把牛腩切丝与青椒同炒，口感柔软兼具清新辣味。',
    'https://images.example.com/qingjiao_niunan_si.jpg',
    'https://videos.example.com/qingjiao_niunan_si.mp4',
    24, 2, 'medium', @cuisine_home,
    480.00, 36.00, 18.00, 28.00
);
SET @recipe_greenpepper_brisket_shreds := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_greenpepper_brisket_shreds, 1, '切丝',
    '牛腩改刀成细丝，加入 12ml 酱油、6g 玉米淀粉与 3g 盐腌 6 分钟；青椒切丝，蒜切片。',
    6, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '牛腩丝可混入 20ml 清水抓匀，炒后更嫩。'
);
SET @step_recipe_greenpepper_brisket_shreds_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_greenpepper_brisket_shreds_1, @tool_board, '切丝'),
    (@step_recipe_greenpepper_brisket_shreds_1, @tool_knife, '切丝'),
    (@step_recipe_greenpepper_brisket_shreds_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_greenpepper_brisket_shreds, 2, '煸香',
    '炒锅倒入 16g 食用油，下蒜片与 6g 花椒炒香，放入牛腩丝大火翻炒 3 分钟。',
    3, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '保持大火使牛腩快速锁汁。'
);
SET @step_recipe_greenpepper_brisket_shreds_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_greenpepper_brisket_shreds_2, @tool_wok, '煸炒'),
    (@step_recipe_greenpepper_brisket_shreds_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_greenpepper_brisket_shreds, 3, '合炒',
    '加入青椒丝、10ml 米醋与 4g 白砂糖，再炒 2 分钟，出锅前淋 3ml 香油。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '米醋要在临出锅前加入，保持酸香。'
);
SET @step_recipe_greenpepper_brisket_shreds_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_greenpepper_brisket_shreds_3, @tool_wok, '翻炒'),
    (@step_recipe_greenpepper_brisket_shreds_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_greenpepper_brisket_shreds, @ing_brisket, '340', 'g', '切丝腌制', 6, 1, NULL, 544.00, 'main'),
    (@recipe_greenpepper_brisket_shreds, @ing_green_pepper, '140', 'g', '切丝', 2, 0, NULL, 28.00, 'auxiliary'),
    (@recipe_greenpepper_brisket_shreds, @ing_garlic, '10', 'g', '切片', 1, 0, NULL, 14.90, 'seasoning'),
    (@recipe_greenpepper_brisket_shreds, @ing_sichuan_pepper, '3', 'g', '煸香', 0, 0, NULL, 9.00, 'seasoning'),
    (@recipe_greenpepper_brisket_shreds, @ing_vinegar, '10', 'ml', '调味', 0, 0, NULL, 1.80, 'seasoning'),
    (@recipe_greenpepper_brisket_shreds, @ing_sugar, '4', 'g', '调味', 0, 0, NULL, 15.48, 'seasoning'),
    (@recipe_greenpepper_brisket_shreds, @ing_soy_sauce, '12', 'ml', '腌制', 0, 0, NULL, 8.64, 'seasoning'),
    (@recipe_greenpepper_brisket_shreds, @ing_cornstarch, '6', 'g', '腌制', 1, 0, NULL, 22.86, 'seasoning'),
    (@recipe_greenpepper_brisket_shreds, @ing_sesame_oil, '3', 'ml', '提香', 0, 0, NULL, 26.52, 'seasoning'),
    (@recipe_greenpepper_brisket_shreds, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_greenpepper_brisket_shreds, @ing_cooking_oil, '20', 'g', '炒制', 0, 0, NULL, 176.80, 'seasoning');

-- Recipe 68: 蒜蓉木耳炒蛋
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '蒜蓉木耳炒蛋',
    '蒜蓉与木耳和鸡蛋同炒，加入青椒增添口感层次。',
    'https://images.example.com/suanrong_muer_chaoegg.jpg',
    'https://videos.example.com/suanrong_muer_chaoegg.mp4',
    14, 2, 'easy', @cuisine_home,
    320.00, 22.00, 18.00, 18.00
);
SET @recipe_garlic_woodear_egg := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_garlic_woodear_egg, 1, '备料',
    '木耳泡发切丝，鸡蛋打散，青椒切丝，蒜切末。',
    3, '常温', JSON_ARRAY('搅拌碗', '砧板', '菜刀'),
    '木耳充分挤干水分，炒制更脆。'
);
SET @step_recipe_garlic_woodear_egg_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_garlic_woodear_egg_1, @tool_mix_bowl, '泡发'),
    (@step_recipe_garlic_woodear_egg_1, @tool_board, '切丝'),
    (@step_recipe_garlic_woodear_egg_1, @tool_knife, '切丝');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_garlic_woodear_egg, 2, '炒蛋',
    '炒锅加 14g 食用油，下蛋液快速翻炒成大块蛋花盛出。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '蛋液六成熟即可出锅保持嫩度。'
);
SET @step_recipe_garlic_woodear_egg_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_garlic_woodear_egg_2, @tool_wok, '炒蛋'),
    (@step_recipe_garlic_woodear_egg_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_garlic_woodear_egg, 3, '合炒',
    '锅内留 8g 油，下蒜末、木耳丝与青椒丝翻炒 2 分钟，倒入蛋花，调入 3g 盐与 4ml 香油，再炒 1 分钟即可。',
    3, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '最后加入香油提升蒜香余韵。'
);
SET @step_recipe_garlic_woodear_egg_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_garlic_woodear_egg_3, @tool_wok, '翻炒'),
    (@step_recipe_garlic_woodear_egg_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_garlic_woodear_egg, @ing_wood_ear, '120', 'g', '泡发切丝', 6, 1, NULL, 30.00, 'main'),
    (@recipe_garlic_woodear_egg, @ing_egg, '3', '个', '打散', 1, 0, NULL, 429.00, 'auxiliary'),
    (@recipe_garlic_woodear_egg, @ing_green_pepper, '80', 'g', '切丝', 2, 0, NULL, 16.00, 'auxiliary'),
    (@recipe_garlic_woodear_egg, @ing_garlic, '12', 'g', '切末', 1, 0, NULL, 17.88, 'seasoning'),
    (@recipe_garlic_woodear_egg, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_garlic_woodear_egg, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_garlic_woodear_egg, @ing_cooking_oil, '22', 'g', '炒制', 0, 0, NULL, 194.48, 'seasoning');

-- Recipe 69: 柠檬青豆鸡丁
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '柠檬青豆鸡丁',
    '青豆与鸡丁加入柠檬汁快炒，口味清爽且带有果香。',
    'https://images.example.com/ningmeng_qingdou_jiding.jpg',
    'https://videos.example.com/ningmeng_qingdou_jiding.mp4',
    16, 2, 'easy', @cuisine_home,
    360.00, 34.00, 18.00, 16.00
);
SET @recipe_lemon_pea_chicken := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_lemon_pea_chicken, 1, '腌制',
    '鸡胸肉切丁加入 12ml 酱油、6g 玉米淀粉与 6ml 柠檬汁抓匀腌 5 分钟；青豆焯水 40 秒备用。',
    5, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗', '汤锅'),
    '鸡丁腌制时加入一点柠檬皮屑更香。'
);
SET @step_recipe_lemon_pea_chicken_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_lemon_pea_chicken_1, @tool_board, '切丁'),
    (@step_recipe_lemon_pea_chicken_1, @tool_knife, '切丁'),
    (@step_recipe_lemon_pea_chicken_1, @tool_mix_bowl, '腌制'),
    (@step_recipe_lemon_pea_chicken_1, @tool_soup_pot, '焯水');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_lemon_pea_chicken, 2, '滑炒',
    '炒锅倒入 16g 食用油，下鸡丁大火滑炒 2 分钟至变白。',
    2, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '保持大火可锁住鸡丁水分。'
);
SET @step_recipe_lemon_pea_chicken_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_lemon_pea_chicken_2, @tool_wok, '滑炒'),
    (@step_recipe_lemon_pea_chicken_2, @tool_spatula, '翻炒');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_lemon_pea_chicken, 3, '合炒',
    '加入青豆与 6g 白砂糖、3g 盐、4ml 香油，再淋入 4ml 柠檬汁，大火翻炒 1 分钟即可。',
    1, '大火', JSON_ARRAY('炒锅', '锅铲'),
    '最终调味后快速出锅，保持青豆色泽。'
);
SET @step_recipe_lemon_pea_chicken_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_lemon_pea_chicken_3, @tool_wok, '翻炒'),
    (@step_recipe_lemon_pea_chicken_3, @tool_spatula, '翻炒');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_lemon_pea_chicken, @ing_chicken, '320', 'g', '切丁腌制', 5, 1, NULL, 512.00, 'main'),
    (@recipe_lemon_pea_chicken, @ing_green_pea, '160', 'g', '焯烫', 1, 0, NULL, 188.80, 'auxiliary'),
    (@recipe_lemon_pea_chicken, @ing_lemon, '1', '个', '榨汁', 1, 0, NULL, 29.00, 'seasoning'),
    (@recipe_lemon_pea_chicken, @ing_sugar, '6', 'g', '调味', 0, 0, NULL, 23.22, 'seasoning'),
    (@recipe_lemon_pea_chicken, @ing_salt, '3', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_lemon_pea_chicken, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_lemon_pea_chicken, @ing_cornstarch, '6', 'g', '腌制', 1, 0, NULL, 22.86, 'seasoning'),
    (@recipe_lemon_pea_chicken, @ing_soy_sauce, '12', 'ml', '腌制', 0, 0, NULL, 8.64, 'seasoning'),
    (@recipe_lemon_pea_chicken, @ing_cooking_oil, '18', 'g', '炒制', 0, 0, NULL, 159.12, 'seasoning');

-- Recipe 70: 西兰花玉米鸡汤
INSERT INTO recipes (
    name, description, image_url, video_url, total_time, servings, difficulty,
    cuisine_id, total_calories, total_protein, total_carbs, total_fat
) VALUES (
    '西兰花玉米鸡汤',
    '西兰花、玉米与鸡丁炖成清甜汤品，补充维生素与蛋白质。',
    'https://images.example.com/xilanhua_yumi_jitang.jpg',
    'https://videos.example.com/xilanhua_yumi_jitang.mp4',
    25, 3, 'easy', @cuisine_home,
    320.00, 30.00, 24.00, 12.00
);
SET @recipe_broccoli_corn_chicken_soup := LAST_INSERT_ID();

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_broccoli_corn_chicken_soup, 1, '切配',
    '鸡胸肉切丁加入 8ml 酱油与 4g 玉米淀粉腌 5 分钟；西兰花掰小朵，玉米粒冲洗沥干。',
    5, '常温', JSON_ARRAY('砧板', '菜刀', '搅拌碗'),
    '鸡丁腌制后加入少量水抓匀更嫩滑。'
);
SET @step_recipe_broccoli_corn_chicken_soup_1 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_broccoli_corn_chicken_soup_1, @tool_board, '切丁'),
    (@step_recipe_broccoli_corn_chicken_soup_1, @tool_knife, '切丁'),
    (@step_recipe_broccoli_corn_chicken_soup_1, @tool_mix_bowl, '腌制');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_broccoli_corn_chicken_soup, 2, '煸香',
    '汤锅加入 8g 食用油，下蒜末煸香 40 秒，倒入鸡丁翻炒 1 分钟。',
    1, '中火', JSON_ARRAY('汤锅'),
    '鸡丁略微变色即可进入下一步。'
);
SET @step_recipe_broccoli_corn_chicken_soup_2 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_broccoli_corn_chicken_soup_2, @tool_soup_pot, '煸香');

INSERT INTO recipe_steps (
    recipe_id, step_number, action, instruction, duration, temperature, tools_used, tips
) VALUES (
    @recipe_broccoli_corn_chicken_soup, 3, '煮汤',
    '加入 800ml 清水、玉米粒与西兰花，小火煮 12 分钟，调入 4g 盐与 4ml 香油即可。',
    12, '小火', JSON_ARRAY('汤锅'),
    '最后 2 分钟可加入葱段增强香气。'
);
SET @step_recipe_broccoli_corn_chicken_soup_3 := LAST_INSERT_ID();

INSERT INTO step_tools (step_id, tool_id, `usage`) VALUES
    (@step_recipe_broccoli_corn_chicken_soup_3, @tool_soup_pot, '煮汤');

INSERT INTO recipe_ingredients (
    recipe_id, ingredient_id, quantity, unit, prep_method, prep_time,
    is_main, substitute, adjusted_calories, ingredient_type
) VALUES
    (@recipe_broccoli_corn_chicken_soup, @ing_chicken, '320', 'g', '切丁腌制', 5, 1, NULL, 512.00, 'main'),
    (@recipe_broccoli_corn_chicken_soup, @ing_broccoli, '220', 'g', '掰小朵', 2, 0, NULL, 74.80, 'auxiliary'),
    (@recipe_broccoli_corn_chicken_soup, @ing_corn_kernel, '160', 'g', '冲洗', 1, 0, NULL, 137.60, 'auxiliary'),
    (@recipe_broccoli_corn_chicken_soup, @ing_garlic, '8', 'g', '切末', 1, 0, NULL, 11.92, 'seasoning'),
    (@recipe_broccoli_corn_chicken_soup, @ing_salt, '4', 'g', '调味', 0, 0, NULL, 0.00, 'seasoning'),
    (@recipe_broccoli_corn_chicken_soup, @ing_sesame_oil, '4', 'ml', '提香', 0, 0, NULL, 35.36, 'seasoning'),
    (@recipe_broccoli_corn_chicken_soup, @ing_soy_sauce, '8', 'ml', '腌制', 0, 0, NULL, 5.76, 'seasoning'),
    (@recipe_broccoli_corn_chicken_soup, @ing_cornstarch, '4', 'g', '腌制', 1, 0, NULL, 15.24, 'seasoning'),
    (@recipe_broccoli_corn_chicken_soup, @ing_cooking_oil, '8', 'g', '煸香', 0, 0, NULL, 70.88, 'seasoning');
