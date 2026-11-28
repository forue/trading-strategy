<template>
  <div class="admin-page">
    <div class="page-card">
      <div class="card-header">
        <span class="card-title">高级功能配额</span>
        <span class="card-note">按账号每日重置 · 0 表示不限次数</span>
      </div>

      <div v-loading="loading" class="feature-list">
        <div v-for="feature in features" :key="feature.key" class="feature-block">
          <div class="feature-head">
            <div class="feature-title">
              <span class="feature-name">{{ feature.name }}</span>
              <span class="feature-key">{{ feature.key }}</span>
            </div>
            <el-button type="primary" plain :loading="saving === feature.key" @click="save(feature)">
              保存
            </el-button>
          </div>
          <p class="feature-desc">{{ feature.description }}</p>

          <div class="quota-rows">
            <div
              v-for="row in feature.roles"
              :key="row.role"
              class="quota-row"
              :class="{ 'is-off': !row.enabled }"
            >
              <div class="quota-role">
                <span class="role-name">{{ row.role === 'ADMIN' ? '管理员' : '普通账号' }}</span>
                <span class="role-key">{{ row.role }}</span>
              </div>
              <div class="quota-limit">
                <el-input-number
                  v-model="row.dailyLimit"
                  :min="0"
                  :max="9999"
                  :step="1"
                  :disabled="!row.enabled"
                  controls-position="right"
                  class="limit-input"
                />
                <span class="unit">次 / 天</span>
                <span class="quota-tip">
                  {{ row.dailyLimit === 0 ? '不限次数' : `每账号每日 ${row.dailyLimit} 次` }}
                </span>
              </div>
              <el-switch v-model="row.enabled" inline-prompt active-text="开" inactive-text="关" />
            </div>
          </div>
        </div>
      </div>

      <el-empty v-if="!loading && !features.length" description="暂无可配置功能" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api/admin'
import type { FeatureQuota } from '@/api/admin'

const loading = ref(false)
const saving = ref('')
const features = ref<FeatureQuota[]>([])

async function load() {
  loading.value = true
  try {
    features.value = await adminApi.getFeatureQuotas()
  } finally {
    loading.value = false
  }
}

async function save(feature: FeatureQuota) {
  saving.value = feature.key
  try {
    await adminApi.saveFeatureQuotas(
      feature.roles.map(row => ({
        featureKey: feature.key,
        role: row.role,
        dailyLimit: row.dailyLimit ?? 0,
        enabled: row.enabled,
      }))
    )
    ElMessage.success(`${feature.name}配额已保存`)
    await load()
  } finally {
    saving.value = ''
  }
}

onMounted(load)
</script>

<style lang="scss" scoped>
.card-header {
  flex-wrap: wrap;
  row-gap: 8px;
}

.card-note {
  font-size: 12px;
  color: var(--text-tertiary);
}

.feature-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.feature-block {
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-md);
  padding: 18px 20px;
}

.feature-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.feature-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.feature-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.feature-key {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-tertiary);
}

.feature-desc {
  margin: 8px 0 16px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-tertiary);
}

.quota-rows {
  display: flex;
  flex-direction: column;
}

.quota-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 0;
  border-top: 1px solid var(--border-subtle);

  &.is-off .role-name {
    color: var(--text-tertiary);
  }
}

.quota-role {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100px;
  flex-shrink: 0;
}

.role-name {
  font-size: 13px;
  color: var(--text-primary);
}

.role-key {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-tertiary);
}

.quota-limit {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.limit-input {
  width: 120px;
}

.quota-tip {
  font-size: 12px;
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 768px) {
  .quota-row {
    flex-wrap: wrap;
    gap: 10px;
  }

  .quota-limit {
    flex: 1 1 200px;
  }
}

@media (max-width: 480px) {
  .feature-block {
    padding: 16px;
  }

  .quota-row {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }

  .quota-role {
    width: auto;
    flex-direction: row;
    align-items: baseline;
    gap: 8px;
  }

  .quota-limit {
    flex: none;
    width: 100%;
    flex-wrap: wrap;
  }
}
</style>
