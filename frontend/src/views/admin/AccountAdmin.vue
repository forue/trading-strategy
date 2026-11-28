<template>
  <div class="admin-page">
    <div class="page-card">
      <div class="card-header">
        <span class="card-title">账号管理</span>
        <div class="card-actions">
          <el-input
            v-model="keyword"
            class="search-input"
            placeholder="搜索用户名 / 邮箱"
            clearable
            @keyup.enter="reload(1)"
            @clear="reload(1)"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-select v-model="roleFilter" class="role-select" placeholder="全部角色" @change="reload(1)">
            <el-option label="全部角色" value="" />
            <el-option label="管理员" value="ADMIN" />
            <el-option label="普通账号" value="USER" />
          </el-select>
          <el-button type="primary" @click="openCreate">
            <el-icon><Plus /></el-icon>
            <span>新建账号</span>
          </el-button>
        </div>
      </div>

      <!-- 桌面端：表格 -->
      <div v-if="!isMobile && users.length" class="responsive-table">
        <el-table :data="users" stripe>
          <el-table-column prop="username" label="用户名" min-width="130" />
          <el-table-column prop="email" label="邮箱" min-width="190">
            <template #default="{ row }">{{ row.email || '—' }}</template>
          </el-table-column>
          <el-table-column prop="role" label="角色" width="104">
            <template #default="{ row }">
              <el-tag :type="row.role === 'ADMIN' ? 'primary' : 'info'" size="small">
                {{ row.role === 'ADMIN' ? '管理员' : '普通账号' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="96">
            <template #default="{ row }">
              <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'danger'" size="small" effect="plain">
                {{ row.status === 'ACTIVE' ? '正常' : '已禁用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="createdAt" label="创建时间" width="150">
            <template #default="{ row }">{{ formatTime(row.createdAt) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="188" fixed="right">
            <template #default="{ row }">
              <div class="table-actions">
                <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
                <el-button link @click="toggleStatus(row)">
                  {{ row.status === 'ACTIVE' ? '禁用' : '启用' }}
                </el-button>
                <el-popconfirm title="删除后不可恢复，确定删除？" width="200" @confirm="removeUser(row)">
                  <template #reference>
                    <el-button link type="danger">删除</el-button>
                  </template>
                </el-popconfirm>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 移动端：条目列表 -->
      <ul v-else-if="isMobile && users.length" class="m-user-list">
        <li v-for="user in users" :key="user.id" class="m-user-row">
          <div class="m-row-head">
            <span class="m-user-name">{{ user.username }}</span>
            <el-tag :type="user.role === 'ADMIN' ? 'primary' : 'info'" size="small">
              {{ user.role === 'ADMIN' ? '管理员' : '普通账号' }}
            </el-tag>
          </div>
          <div class="m-row-meta">
            <span>{{ user.email || '未填写邮箱' }}</span>
            <span>{{ user.status === 'ACTIVE' ? '正常' : '已禁用' }} · {{ formatTime(user.createdAt) }}</span>
          </div>
          <div class="m-row-actions">
            <el-button size="small" @click="openEdit(user)">编辑</el-button>
            <el-button size="small" @click="toggleStatus(user)">
              {{ user.status === 'ACTIVE' ? '禁用' : '启用' }}
            </el-button>
            <el-popconfirm title="删除后不可恢复，确定删除？" width="200" @confirm="removeUser(user)">
              <template #reference>
                <el-button size="small" type="danger" plain>删除</el-button>
              </template>
            </el-popconfirm>
          </div>
        </li>
      </ul>

      <el-empty v-else :description="loading ? '加载中…' : '暂无账号'" />

      <div v-if="total > pageSize" class="pagination-bar">
        <el-pagination
          :current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="reload"
        />
      </div>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑账号' : '新建账号'"
      width="460px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" :disabled="!!editingId" placeholder="登录用户名" />
        </el-form-item>
        <el-form-item :label="editingId ? '重置密码' : '密码'">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="editingId ? '留空则不修改' : '至少 6 位'"
          />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="选填" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" placeholder="选填" />
        </el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="form.role">
            <el-radio value="USER">普通账号</el-radio>
            <el-radio value="ADMIN">管理员</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio value="ACTIVE">正常</el-radio>
            <el-radio value="DISABLED">禁用</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import { adminApi } from '@/api/admin'
import type { AdminUser, RoleKey } from '@/api/admin'
import { useBreakpoint } from '@/composables/useBreakpoint'

const { isMobile } = useBreakpoint()

const users = ref<AdminUser[]>([])
const loading = ref(false)
const saving = ref(false)
const keyword = ref('')
const roleFilter = ref('')
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({
  username: '',
  password: '',
  email: '',
  phone: '',
  role: 'USER' as RoleKey,
  status: 'ACTIVE',
})

function formatTime(value: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '—'
}

async function reload(nextPage = page.value) {
  loading.value = true
  try {
    const res = await adminApi.listUsers({
      keyword: keyword.value.trim(),
      role: roleFilter.value,
      page: nextPage,
      size: pageSize.value,
    })
    users.value = res.items || []
    total.value = res.total || 0
    page.value = res.page || nextPage
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.username = ''
  form.password = ''
  form.email = ''
  form.phone = ''
  form.role = 'USER'
  form.status = 'ACTIVE'
}

function openCreate() {
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(row: AdminUser) {
  editingId.value = row.id
  form.username = row.username
  form.password = ''
  form.email = row.email || ''
  form.phone = row.phone || ''
  form.role = row.role
  form.status = row.status
  dialogVisible.value = true
}

async function submit() {
  const username = form.username.trim()
  if (!editingId.value && !username) {
    ElMessage.warning('请输入用户名')
    return
  }
  if (form.password && form.password.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  if (!editingId.value && !form.password) {
    ElMessage.warning('请设置初始密码')
    return
  }

  const payload = {
    email: form.email.trim(),
    phone: form.phone.trim(),
    role: form.role,
    status: form.status,
    ...(editingId.value
      ? (form.password ? { password: form.password } : {})
      : { username, password: form.password }),
  }

  saving.value = true
  try {
    if (editingId.value) {
      await adminApi.updateUser(editingId.value, payload)
    } else {
      await adminApi.createUser(payload)
    }
    ElMessage.success(editingId.value ? '账号已更新' : '账号已创建')
    dialogVisible.value = false
    await reload(editingId.value ? page.value : 1)
  } finally {
    saving.value = false
  }
}

async function toggleStatus(row: AdminUser) {
  const next = row.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE'
  await adminApi.updateUser(row.id, { status: next })
  ElMessage.success(next === 'ACTIVE' ? '账号已启用' : '账号已禁用')
  await reload()
}

async function removeUser(row: AdminUser) {
  await adminApi.deleteUser(row.id)
  ElMessage.success('账号已删除')
  if (users.value.length === 1 && page.value > 1) {
    await reload(page.value - 1)
  } else {
    await reload()
  }
}

onMounted(() => reload(1))
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
}

.search-input {
  width: 200px;
}

.role-select {
  width: 120px;
}

.table-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.m-user-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.m-user-row {
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-md);
  padding: 14px;
}

.m-row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;

  .m-user-name {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.m-row-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-tertiary);
  word-break: break-all;
}

.m-row-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ctrl-gap);
  margin-top: 12px;
}

@media (max-width: 768px) {
  .search-input {
    width: 160px;
  }
}

@media (max-width: 480px) {
  .card-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .search-input,
  .role-select {
    flex: 1 1 140px;
    width: auto;
  }

  .pagination-bar {
    justify-content: center;
  }
}
</style>
