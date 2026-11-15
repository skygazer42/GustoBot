<template>
  <div class="recipe-meta">
    <span><UiIcon name="clock" />{{ recipe.minutes }} 分钟</span>
    <span><UiIcon name="people" />{{ recipe.servings }} 人份</span>
  </div>
</template>

<script setup lang="ts">
import { recipe } from "../data/recipe";
import UiIcon from "./UiIcon.vue";
</script>
