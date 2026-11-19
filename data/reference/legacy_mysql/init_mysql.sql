-- GustoBot MySQL schema initialization
-- Creates recipe management tables with UTF-8 support.

CREATE DATABASE IF NOT EXISTS recipe_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE recipe_db;
SET NAMES utf8mb4;

-- Drop tables for idempotent initialization during container bootstrap.
DROP TABLE IF EXISTS step_tools;
DROP TABLE IF EXISTS recipe_steps;
DROP TABLE IF EXISTS recipe_ingredients;
DROP TABLE IF EXISTS recipes;
DROP TABLE IF EXISTS cooking_tools;
DROP TABLE IF EXISTS ingredients;
DROP TABLE IF EXISTS cuisines;

CREATE TABLE cuisines (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    cooking_style TEXT,
    typical_tools JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE cooking_tools (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    type ENUM('pot', 'pan', 'knife', 'oven', 'other') DEFAULT 'other',
    material VARCHAR(50),
    capacity VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE ingredients (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    category VARCHAR(100),
    calories DECIMAL(10,2) DEFAULT 0.00,
    protein DECIMAL(10,2) DEFAULT 0.00,
    carbs DECIMAL(10,2) DEFAULT 0.00,
    fat DECIMAL(10,2) DEFAULT 0.00,
    storage_method VARCHAR(100),
    shelf_life INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_ingredient_category (category)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE recipes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    image_url VARCHAR(500),
    video_url VARCHAR(500),
    total_time INT DEFAULT 0,
    servings INT DEFAULT 4,
    difficulty ENUM('easy', 'medium', 'hard') DEFAULT 'easy',
    cuisine_id INT,
    total_calories DECIMAL(10,2) DEFAULT 0.00,
    total_protein DECIMAL(10,2) DEFAULT 0.00,
    total_carbs DECIMAL(10,2) DEFAULT 0.00,
    total_fat DECIMAL(10,2) DEFAULT 0.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE INDEX idx_recipe_name (name),
    INDEX idx_recipe_cuisine (cuisine_id),
    CONSTRAINT fk_recipes_cuisine
        FOREIGN KEY (cuisine_id) REFERENCES cuisines(id)
        ON DELETE SET NULL
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE recipe_steps (
    id INT AUTO_INCREMENT PRIMARY KEY,
    recipe_id INT NOT NULL,
    step_number INT NOT NULL,
    action VARCHAR(100) NOT NULL,
    instruction TEXT NOT NULL,
    duration INT DEFAULT 0,
    temperature VARCHAR(50),
    tools_used JSON,
    tips TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_recipe_step (recipe_id, step_number),
    INDEX idx_recipe_steps_recipe (recipe_id),
    CONSTRAINT fk_recipe_steps_recipe
        FOREIGN KEY (recipe_id) REFERENCES recipes(id)
        ON DELETE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE recipe_ingredients (
    id INT AUTO_INCREMENT PRIMARY KEY,
    recipe_id INT NOT NULL,
    ingredient_id INT NOT NULL,
    quantity VARCHAR(100) NOT NULL,
    unit VARCHAR(50),
    prep_method VARCHAR(100),
    prep_time INT DEFAULT 0,
    is_main BOOLEAN DEFAULT FALSE,
    substitute VARCHAR(255),
    adjusted_calories DECIMAL(10,2) DEFAULT 0.00,
    ingredient_type ENUM('main', 'auxiliary', 'seasoning') DEFAULT 'auxiliary',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_recipe_ingredients_recipe (recipe_id),
    INDEX idx_recipe_ingredients_main (recipe_id, is_main),
    INDEX idx_recipe_ingredients_type (recipe_id, ingredient_type),
    CONSTRAINT fk_recipe_ingredients_recipe
        FOREIGN KEY (recipe_id) REFERENCES recipes(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_recipe_ingredients_ingredient
        FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
        ON DELETE RESTRICT
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE step_tools (
    id INT AUTO_INCREMENT PRIMARY KEY,
    step_id INT NOT NULL,
    tool_id INT NOT NULL,
    `usage` VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_step_tool (step_id, tool_id),
    INDEX idx_step_tools_step (step_id),
    INDEX idx_step_tools_tool (tool_id),
    CONSTRAINT fk_step_tools_step
        FOREIGN KEY (step_id) REFERENCES recipe_steps(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_step_tools_tool
        FOREIGN KEY (tool_id) REFERENCES cooking_tools(id)
        ON DELETE RESTRICT
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;
