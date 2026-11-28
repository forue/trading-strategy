<template>
  <div class="admin-page">
    <div class="page-card">
      <div class="card-header">
        <span class="card-title">页面访问权限</span>
        <div class="card-actions">
          <el-radio-group v-model="role" @change="onRoleChange">
            <el-radio-button value="USER">普通账号</el-radio-button>
            <el-radio-button value="ADMIN">管理员</el-radio-button>
          </el-radio-group>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        </div>
      </div>

      <p class="perm-hint">
        勾选后该角色才能在侧栏看到并进入对应页面；未勾选的页面即使手动输入地址也会被路由拦回。
        后台管理三项固定只对管理员开放，不可勾选。
      </p>

      <div v-loading="loading" class="perm-groups">
        <section v-for="group in groups" :key="group.name" class="perm-group">
          <div class="perm-group-title">
            <span>{{ group.name }}</span>
            <span class="perm-count">{{ group.routes.filter(r => isChecked(r.path)).length }}/{{ group.routes.length }}</span>
          </div>
          <div class="perm-rows">
            <div
              v-for="item in group.routes"
              :key="item.path"
              class="perm-row"
              :class="{ 'is-locked': isLocked(item.path) }"
            >
              <div class="perm-main">
                <span class="perm-name">{{ item.name }}</span>
                <span class="perm-path">{{ item.path }}</span>
              </div>
              <div class="perm-side">
                <el-tag v-if="isLocked(item.path)" size="small" type="warning" effect="plain">仅管理员</el-tag>
                <el-switch
                  :model-value="isChecked(item.path)"
                  :disabled="isLocked(item.path)"
                  @change="(value) => toggle(item.path, value)"
                />
              </div>
            </div>
          </div>
        </section>
      </div>

      <el-empty v-if="!loading && !groups.length" description="暂无可配置页面" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api/admin'
import type { RoleKey, RouteDef, RoutePermissionData } from '@/api/admin'

const loading = ref(false)
const saving = ref(false)
const data = ref<RoutePermissionData | null>(null)
const role = ref<RoleKey>('USER')
const selected = ref<string[]>([])

const groups = computed(() => {
  const routes: RouteDef[] = data.value?.routes || []
  const order: string[] = []
  const buckets: Record<string, RouteDef[]> = {}
  for (const route of routes) {
    if (!buckets[route.group]) {
      buckets[route.group] = []
      order.push(route.group)
    }
    buckets[route.group].push(route)
  }
  return order.map(name => ({ name, routes: buckets[name] }))
})

function isLocked(path: string): boolean {
  return (data.value?.lockedPaths || []).includes(path)
}

function isChecked(path: string): boolean {
  if (isLocked(path)) return role.value === 'ADMIN'
  return selected.value.includes(path)
}

function onRoleChange() {
  selected.value = [...(data.value?.permissions?.[role.value] || [])]
}

function toggle(path: string, value: string | number | boolean) {
  if (value) {
    if (!selected.value.includes(path)) selected.value = [...selected.value, path]
  } else {
    selected.value = selected.value.filter(item => item !== path)
  }
}

async function load() {
  loading.value = true
  try {
    data.value = await adminApi.getRoutePermissions()
    onRoleChange()
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!selected.value.length) {
    ElMessage.warning('至少需要保留一个可访问页面')
    return
  }
  saving.value = true
  try {
    data.value = await adminApi.saveRoutePermissions(role.value, selected.value)
    onRoleChange()
    ElMessage.success('页面权限已保存')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style lang="scss" scoped>
.card-header {
  flex-wrap: wrap;
  row-gap: 8px;
}

.card-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: var(--ctrl-gap);
}

.perm-hint {
  margin: 0 0 20px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-tertiary);
}

.perm-groups {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.perm-group-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-subtle);
}

.perm-count {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 400;
  color: var(--text-tertiary);
}

.perm-rows {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 32px;
}

.perm-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 48px;
  border-bottom: 1px solid var(--border-subtle);

  &.is-locked .perm-name {
    color: var(--text-tertiary);
  }
}

.perm-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.perm-name {
  font-size: 13px;
  color: var(--text-primary);
}

.perm-path {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-tertiary);
}

.perm-side {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

@media (max-width: 768px) {
  .perm-rows {
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
  }
}

@media (max-width: 480px) {
  .card-actions {
    width: 100%;
    justify-content: space-between;
  }
}
</style>
