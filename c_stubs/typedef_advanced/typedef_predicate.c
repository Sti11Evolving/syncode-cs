typedef int (*Predicate)(int value);
typedef Predicate IntPredicate;

static int is_even(int value);

int count_matching(const int values[], int length, IntPredicate predicate);

int main(void)
{
    int values[] = {2, 5, 8, 11, 14};
    int count;

    count = count_matching(values, 5, is_even);

    return 0;
}

static int is_even(int value)
{
    return value % 2 == 0;
}

// Count values accepted by the predicate.
int count_matching(const int values[], int length, IntPredicate predicate)
{
