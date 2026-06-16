def compute_diagonal_sum(matrix):
    total = 0
    for i in range(len(matrix)):
        total += matrix[i][i]
    return total